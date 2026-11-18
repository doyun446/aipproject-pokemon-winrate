"""Train, calibrate, and evaluate from seeded Showdown simulation records."""

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from copy import deepcopy
from pathlib import Path

import numpy as np
import torch
from torch.nn import functional as F

from .catalog import Catalog, swap_sides
from .features import Encoder
from .model import CHECKPOINT_VERSION, LogisticBaseline, MatchMLP, catalog_hash


def load_examples(paths, catalog, *, require_alternate_sp=False):
    encoder = Encoder(catalog)
    features, pokemon, sets = [], [], []
    wins, health, has_health, pairs, modes = [], [], [], [], []
    mirrors, actions, damage_logits = [], [], []
    group_pairs = {}
    known_points = defaultdict(set)
    if require_alternate_sp:
        for (pokemon_id, _), points in encoder.stat_points.items():
            base_species = catalog.pokemon[pokemon_id]["base_species"]
            known_points[base_species].add(points)

    def append(state, action, win, hp, pair):
        numeric, species, set_ids = encoder.encode(state, action)
        features.append(numeric)
        pokemon.append(species)
        sets.append(set_ids)
        wins.append(win)
        health.append(0.0 if hp is None else hp / 100)
        has_health.append(hp is not None)
        pairs.append(pair)
        modes.append(state["mode"])

    for path in paths:
        with path.open(encoding="utf-8-sig") as stream:
            for line_number, line in enumerate(stream, 1):
                if not line.strip():
                    continue
                try:
                    record = json.loads(line)
                    scenario, action = record["scenario"], record["action"]
                    if require_alternate_sp:
                        variants = [
                            encoder._variant(slot) for slot in scenario["own"] + scenario["foe"]
                        ]
                        if any(points is None for _, points in variants):
                            raise ValueError(
                                "alternate Stat Point trial must override every slot"
                            )
                        if any(
                            points in known_points[catalog.pokemon[key[0]]["base_species"]]
                            for key, points in variants
                        ):
                            continue
                    win, hp = float(record["win"]), float(record["hp_after"])
                    if not (0 <= win <= 1 and 0 <= hp <= 100):
                        raise ValueError("win or HP target is out of range")
                    opponents = (
                        catalog.pokemon[scenario[side][0]["pokemon"]]["base_species"]
                        for side in ("own", "foe")
                    )
                    pair = "|".join(sorted(opponents))
                    group = (scenario["mode"], record["group"])
                    if group_pairs.setdefault(group, pair) != pair:
                        raise ValueError(
                            "one simulation group spans multiple active matchups"
                        )
                    index = len(wins)
                    append(scenario, action, win, hp, pair)
                    actions.append(action)
                    mirrors.append((index, index + 1 if action == "auto" else index))
                    damage_logits.append(
                        encoder.damage_rule_logit(scenario) if action == "auto" else 0
                    )
                    if action == "auto":
                        append(swap_sides(scenario), action, 1 - win, None, pair)
                except (KeyError, TypeError, ValueError, IndexError) as error:
                    raise ValueError(
                        f"Bad simulation record at {path}:{line_number}: {error}"
                    ) from error

    if not wins:
        raise ValueError("No simulation records were supplied.")
    return (
        torch.from_numpy(np.stack(features)),
        torch.tensor(pokemon, dtype=torch.long),
        torch.tensor(sets, dtype=torch.long),
        torch.tensor(wins, dtype=torch.float32),
        torch.tensor(health, dtype=torch.float32),
        torch.tensor(has_health, dtype=torch.bool),
        np.asarray(pairs),
        np.asarray(modes),
        np.asarray(mirrors),
        actions,
        torch.tensor(damage_logits, dtype=torch.float32),
    )


def split_matchups(pairs, seed):
    def rank(pair):
        return hashlib.sha256(f"{seed}:{pair}".encode()).digest()

    unique = sorted(set(pairs), key=rank)
    if len(unique) < 3:
        raise ValueError(
            "At least three distinct unordered active matchups are required."
        )
    held_out = max(1, int(len(unique) * 0.15))
    validation = set(unique[:held_out])
    test = set(unique[held_out : 2 * held_out])
    return np.asarray(
        [
            "validation" if pair in validation else "test" if pair in test else "train"
            for pair in pairs
        ]
    )


def predict_outputs(model, inputs, indices):
    model.eval()
    wins, hp = [], []
    with torch.inference_mode():
        for batch in indices.split(2048):
            logits, health = model(*(column[batch] for column in inputs))
            wins.append(logits)
            if health is not None:
                hp.append(torch.sigmoid(health))
    return torch.cat(wins), torch.cat(hp) if hp else None


def evaluation_outputs(model, inputs, rows):
    originals = torch.from_numpy(rows[:, 0])
    reversed_rows = torch.from_numpy(rows[:, 1])
    duel = originals != reversed_rows
    direct, hp = predict_outputs(model, inputs, originals)
    reverse = torch.zeros_like(direct)
    if torch.any(duel):
        reverse[duel], _ = predict_outputs(model, inputs, reversed_rows[duel])
    return direct, reverse, duel, hp


def probabilities(direct, reverse, duel, temperature=1.0):
    forward = torch.sigmoid(direct / temperature)
    return torch.where(
        duel, (forward + 1 - torch.sigmoid(reverse / temperature)) * 0.5, forward
    )


def fit(
    model, inputs, wins, health, has_health, train, validation, epochs, seed, batch_size
):
    use_health = isinstance(model, MatchMLP)
    optimizer = torch.optim.AdamW(
        model.parameters(), lr=0.002 if use_health else 0.015, weight_decay=0.015
    )
    order = torch.Generator().manual_seed(seed)
    original_validation = torch.from_numpy(validation[:, 0])
    best_loss = float("inf")
    best_weights = deepcopy(model.state_dict())
    patience = 8
    for epoch in range(epochs):
        model.train()
        shuffled = train[torch.randperm(len(train), generator=order)]
        for batch in shuffled.split(batch_size):
            optimizer.zero_grad(set_to_none=True)
            logits, hp = model(*(column[batch] for column in inputs))
            loss = F.binary_cross_entropy_with_logits(logits, wins[batch])
            if use_health:
                eligible = has_health[batch]
                # Mirrored duel rows regularize only the win head.
                if torch.any(eligible):
                    loss += 0.8 * F.mse_loss(
                        torch.sigmoid(hp[eligible]), health[batch][eligible]
                    )
            loss.backward()
            optimizer.step()

        direct, reverse, duel, _ = evaluation_outputs(model, inputs, validation)
        validation_loss = float(
            F.binary_cross_entropy(
                probabilities(direct, reverse, duel), wins[original_validation]
            )
        )
        if validation_loss < best_loss - 0.0001:
            best_loss = validation_loss
            best_weights = deepcopy(model.state_dict())
            stale = 0
        else:
            stale += 1
        if epoch in (0, epochs - 1) or (epoch + 1) % 10 == 0:
            print(
                f"{type(model).__name__} {epoch + 1}/{epochs} validation log loss {validation_loss:.4f}",
                flush=True,
            )
        if stale >= patience:
            break
    model.load_state_dict(best_weights)


def calibrate(direct, reverse, duel, wins, modes):
    temperatures = {}
    for mode in ("duel", "team"):
        indices = modes == mode
        if not np.any(indices):
            temperatures[mode] = 1.0
            continue
        logits, mirrored, mask, outcomes = (
            direct[indices],
            reverse[indices],
            duel[indices],
            wins[indices],
        )
        candidates = sorted(
            {1.0, *np.geomspace(0.55, 3.0, 41).tolist()},
            key=lambda value: abs(value - 1.0),
        )
        temperatures[mode] = min(
            candidates,
            key=lambda value: float(
                F.binary_cross_entropy(
                    probabilities(logits, mirrored, mask, value), outcomes
                )
            ),
        )
    return temperatures


def score(predicted, wins, hp_predicted=None, hp=None):
    calibration = []
    bins = torch.clamp((predicted * 10).long(), max=9)
    for bin_number in range(10):
        inside_bin = bins == bin_number
        if torch.any(inside_bin):
            calibration.append(
                {
                    "count": int(inside_bin.sum()),
                    "predicted": float(predicted[inside_bin].mean()),
                    "observed": float(wins[inside_bin].mean()),
                }
            )
    decisive = wins != 0.5
    result = {
        "n": len(wins),
        "brier": float(F.mse_loss(predicted, wins)),
        "log_loss": float(F.binary_cross_entropy(predicted, wins)),
        "accuracy": float(
            ((predicted[decisive] >= 0.5) == (wins[decisive] == 1)).float().mean()
        )
        if torch.any(decisive)
        else None,
        "calibration": calibration,
    }
    if hp_predicted is not None:
        result["hp_mae"] = float(F.l1_loss(hp_predicted, hp) * 100)
    close = (predicted >= 0.4) & (predicted <= 0.6)
    if torch.any(close):
        result["predicted_40_60"] = {
            "n": int(close.sum()),
            "brier": float(F.mse_loss(predicted[close], wins[close])),
            "log_loss": float(F.binary_cross_entropy(predicted[close], wins[close])),
        }
    return result


def normalization(numeric, train):
    samples = numeric[train]
    return samples.mean(dim=0), samples.std(dim=0, unbiased=False).clamp(min=0.08)


def fit_calibrated(model, inputs, targets, train, validation, modes, args):
    wins, health, has_health = targets
    fit(
        model,
        inputs,
        wins,
        health,
        has_health,
        train,
        validation,
        args.epochs,
        args.seed,
        args.batch_size,
    )
    direct, reverse, duel, _ = evaluation_outputs(model, inputs, validation)
    original = validation[:, 0]
    return calibrate(direct, reverse, duel, wins[original], modes[original])


def evaluate(model, inputs, wins, health, rows, modes, temperatures):
    direct, reverse, duel, hp = evaluation_outputs(model, inputs, rows)
    original = rows[:, 0]
    modes = modes[original]
    temperature = torch.tensor([temperatures[mode] for mode in modes])
    predicted = probabilities(direct, reverse, duel, temperature)
    results = {}
    for mode in ("overall", "duel", "team"):
        mask = np.ones(len(rows), dtype=bool) if mode == "overall" else modes == mode
        if np.any(mask):
            results[mode] = score(
                predicted[mask],
                wins[original][mask],
                hp[mask] if hp is not None else None,
                health[original][mask],
            )
    return results


def learning_curve(make_model, data, train_pairs, partitions, full_metrics, args):
    numeric, pokemon, sets, wins, health, has_health, pairs, modes, mirrors, _, _ = data
    validation, test = partitions
    train_pairs = sorted(
        train_pairs,
        key=lambda pair: hashlib.sha256(f"curve:{args.seed}:{pair}".encode()).digest(),
    )
    curve = []
    for fraction in (0.25, 0.50, 1.00):
        pair_count = max(1, round(len(train_pairs) * fraction))
        picked = np.isin(pairs, train_pairs[:pair_count])
        row = {
            "fraction": fraction,
            "train_trials": int(picked[mirrors[:, 0]].sum()),
            "train_matchups": pair_count,
        }
        if fraction == 1:
            results = {
                mode: full_metrics[mode]["mlp"]
                for mode in ("overall", "duel", "team")
                if "mlp" in full_metrics[mode]
            }
        else:
            print(f"Learning curve: {fraction:.0%} of training matchups", flush=True)
            torch.manual_seed(args.seed)
            model = make_model()
            train = torch.from_numpy(np.flatnonzero(picked))
            mean, scale = normalization(numeric, train)
            inputs = ((numeric - mean) / scale, pokemon, sets)
            temperatures = fit_calibrated(
                model,
                inputs,
                (wins, health, has_health),
                train,
                validation,
                modes,
                args,
            )
            results = evaluate(model, inputs, wins, health, test, modes, temperatures)
        for mode, result in results.items():
            row[mode] = {
                metric: result[metric] for metric in ("brier", "log_loss", "accuracy")
            }
        curve.append(row)
    return curve


def run(args):
    torch.set_num_threads(args.threads)
    torch.manual_seed(args.seed)
    catalog = Catalog(args.catalog)
    print("Reading and encoding simulation trials", flush=True)
    data = load_examples(args.data, catalog)
    (
        numeric,
        pokemon,
        sets,
        wins,
        health,
        has_health,
        pairs,
        modes,
        mirrors,
        actions,
        damage,
    ) = data
    split = split_matchups(pairs, args.seed)
    train = torch.from_numpy(np.flatnonzero(split == "train"))
    original = mirrors[:, 0]
    validation = mirrors[split[original] == "validation"]
    test = mirrors[split[original] == "test"]
    validation_original, test_original = validation[:, 0], test[:, 0]
    mean, scale = normalization(numeric, train)
    inputs = ((numeric - mean) / scale, pokemon, sets)
    counts = {
        name: int(np.sum(split[original] == name))
        for name in ("train", "validation", "test")
    }
    pair_partitions = {name: sorted(set(pairs[split == name])) for name in counts}
    metrics = {
        "data": {
            "seed": args.seed,
            "trials": len(original),
            "split": counts,
            "unique_matchups": {
                name: len(matchups) for name, matchups in pair_partitions.items()
            },
            "matchup_partitions": pair_partitions,
            "by_action": dict(Counter(actions)),
            "by_mode": dict(Counter(modes[original])),
            "evaluation": "held-out unordered active base-species pairs; per trial, conditional on sampled sets",
        },
        "overall": {},
        "duel": {},
        "team": {},
    }
    feature_count = numeric.shape[1]

    def make_model():
        return MatchMLP(feature_count, len(catalog.pokemon), len(catalog.sets))

    mlp = make_model()
    for name, model in (("mlp", mlp), ("logistic", LogisticBaseline(feature_count))):
        temperatures = fit_calibrated(
            model, inputs, (wins, health, has_health), train, validation, modes, args
        )
        for mode, result in evaluate(
            model, inputs, wins, health, test, modes, temperatures
        ).items():
            metrics[mode][name] = result
        if name == "mlp":
            bundle = {
                "version": CHECKPOINT_VERSION,
                "catalog_hash": catalog_hash(args.catalog),
                "state_dict": model.state_dict(),
                "feature_mean": mean,
                "feature_scale": scale,
                "temperature": temperatures,
            }

    duel_test = modes[test_original] == "duel"
    if np.any(duel_test):
        validation_logits = damage[split[original] == "validation"]
        blank = torch.zeros_like(validation_logits)
        rule_scale = calibrate(
            validation_logits,
            blank,
            blank.bool(),
            wins[validation_original],
            modes[validation_original],
        )["duel"]
        rule_predictions = torch.sigmoid(
            damage[split[original] == "test"][duel_test] / rule_scale
        )
        metrics["duel"]["damage_rule"] = score(
            rule_predictions, wins[test_original][duel_test]
        )

    if args.alternate_sp_data:
        print("Evaluating unseen Stat Point allocations", flush=True)
        (
            alt_numeric,
            alt_pokemon,
            alt_sets,
            alt_wins,
            alt_health,
            _,
            alt_pairs,
            alt_modes,
            alt_rows,
            _,
            _,
        ) = load_examples(args.alternate_sp_data, catalog, require_alternate_sp=True)
        alt_inputs = ((alt_numeric - mean) / scale, alt_pokemon, alt_sets)
        metrics["alternate_sp"] = {
            "unique_matchups": len(set(alt_pairs)),
            **evaluate(
                mlp,
                alt_inputs,
                alt_wins,
                alt_health,
                alt_rows,
                alt_modes,
                bundle["temperature"],
            ),
        }
    if args.learning_curve:
        metrics["learning_curve"] = learning_curve(
            make_model,
            data,
            pair_partitions["train"],
            (validation, test),
            metrics,
            args,
        )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.metrics.parent.mkdir(parents=True, exist_ok=True)
    model_temp = args.output.with_suffix(args.output.suffix + ".tmp")
    metrics_temp = args.metrics.with_suffix(args.metrics.suffix + ".tmp")
    torch.save(bundle, model_temp)
    metrics_temp.write_text(
        json.dumps(metrics, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    model_temp.replace(args.output)
    metrics_temp.replace(args.metrics)
    print(f"Saved {args.output} and {args.metrics}", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, default=Path("data/catalog.json"))
    parser.add_argument("--data", type=Path, nargs="+", required=True)
    parser.add_argument("--output", type=Path, default=Path("model/model.pt"))
    parser.add_argument("--metrics", type=Path, default=Path("model/metrics.json"))
    parser.add_argument("--epochs", type=int, default=40)
    parser.add_argument("--batch-size", type=int, default=1024)
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--learning-curve", action="store_true")
    parser.add_argument("--alternate-sp-data", type=Path, nargs="+")
    args = parser.parse_args()
    if min(args.epochs, args.batch_size, args.threads) < 1:
        parser.error("epochs, batch size, and threads must be positive")
    run(args)


if __name__ == "__main__":
    main()
