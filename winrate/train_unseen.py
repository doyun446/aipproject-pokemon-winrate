"""Evaluate unseen Pokémon on 1:1 simulator trials and fit a masked checkpoint."""

import argparse
import json
from pathlib import Path

import numpy as np
import torch

from .catalog import Catalog
from .model import CHECKPOINT_VERSION, LogisticBaseline, MatchMLP, catalog_hash
from .train import (
    evaluation_outputs,
    fit_calibrated,
    load_examples,
    normalization,
    probabilities,
    score,
    split_matchups,
)


HOLDOUT_SPECIES = ("absol", "primarina", "greninja", "raichu", "starmie")
MASK_RATE = 0.15


class MaskedMatchMLP(MatchMLP):
    """Train occasionally without a slot's learned identity."""

    def __init__(self, feature_count, pokemon_count, set_count, *, seed):
        super().__init__(feature_count, pokemon_count, set_count)
        self.mask_rng = torch.Generator().manual_seed(seed)

    def forward(self, features, pokemon, sets):
        if self.training:
            masked = (
                torch.rand(pokemon.shape, generator=self.mask_rng) < MASK_RATE
            ) & (pokemon != 0)
            pokemon = pokemon.masked_fill(masked, 0)
            sets = sets.masked_fill(masked, 0)
        return super().forward(features, pokemon, sets)


def base_species_ids(catalog, species):
    return [
        index
        for key, index in catalog.pokemon_ids.items()
        if catalog.pokemon[key]["base_species"] == species
    ]


def partitions(pairs, duel, unseen, seed, mirrors):
    eligible = duel & ~unseen
    split = np.full(len(pairs), "", dtype="<U10")
    split[eligible] = split_matchups(pairs[eligible], seed)
    original = mirrors[:, 0]
    train = torch.from_numpy(np.flatnonzero(split == "train"))
    val = mirrors[split[original] == "validation"]
    test = mirrors[split[original] == "test"]
    if not len(train) or not len(val) or not len(test):
        raise ValueError(
            "The duel data must supply nonempty train, validation, and test splits."
        )
    names = ("train", "validation", "test")
    counts = {name: int((split[original] == name).sum()) for name in names}
    unique = {name: len(set(pairs[split == name])) for name in names}
    return train, val, test, counts, unique


def evaluate_duels(model, inputs, targets, mirrors, calibrated, subgroups=None):
    wins, health, _ = targets
    direct, reverse, duel, hp = evaluation_outputs(model, inputs, mirrors)
    prediction = probabilities(direct, reverse, duel, calibrated["duel"])
    original = mirrors[:, 0]

    def results(selection):
        return score(
            prediction[selection],
            wins[original][selection],
            hp[selection] if hp is not None else None,
            health[original][selection],
        )

    result = results(slice(None))
    subgroup_results = {
        name: results(selection)
        for name, selection in (subgroups or {}).items()
        if np.any(selection)
    }
    return result, subgroup_results


def run(args):
    torch.set_num_threads(args.threads)
    catalog = Catalog(args.catalog)
    held_ids = {base: base_species_ids(catalog, base) for base in HOLDOUT_SPECIES}
    if not all(held_ids.values()):
        raise ValueError(
            f"The catalog must include these base species: {HOLDOUT_SPECIES}"
        )

    print("Reading seeded Showdown trials", flush=True)
    data = load_examples(args.data, catalog)
    numeric, pokemon, sets, wins, health, has_health, pairs, modes, mirrors, _, _ = data
    targets = (wins, health, has_health)
    duel = modes == "duel"
    held_slots = torch.from_numpy(
        np.isin(pokemon.numpy(), [index for ids in held_ids.values() for index in ids])
    )
    unseen = held_slots.any(dim=1).numpy()
    oov = mirrors[(duel & unseen)[mirrors[:, 0]]]
    if not len(oov):
        raise ValueError("The input needs 1:1 trials using the held-out species.")
    oov_original = oov[:, 0]
    slot_count = held_slots[oov_original].sum(dim=1).numpy()
    subgroups = {"one": slot_count == 1, "two": slot_count == 2}
    by_species = {
        base: np.isin(pokemon[oov_original].numpy(), ids).any(axis=1)
        for base, ids in held_ids.items()
    }
    if not all(selection.any() for selection in by_species.values()):
        raise ValueError("The input needs trials for each held-out base species.")

    train, val, test, counts, unique = partitions(
        pairs, duel, unseen, args.seed, mirrors
    )
    mean, scale = normalization(numeric, train)
    normalized = (numeric - mean) / scale
    inputs = (normalized, pokemon, sets)
    oov_inputs = (
        normalized,
        pokemon.masked_fill(held_slots, 0),
        sets.masked_fill(held_slots, 0),
    )
    model_size = (numeric.shape[1], len(catalog.pokemon), len(catalog.sets))
    metrics = {
        "data": {
            "seed": args.seed,
            "mask_rate": MASK_RATE,
            "mode": "duel",
            "holdout_base_species": list(HOLDOUT_SPECIES),
            "split": {
                "train": counts["train"],
                "validation": counts["validation"],
                "test_known": counts["test"],
                "test_unseen": len(oov),
            },
            "unique_matchups": {
                "train": unique["train"],
                "validation": unique["validation"],
                "test_known": unique["test"],
                "test_unseen": len(set(pairs[oov_original])),
            },
            "unseen_species_trials": {
                base: int(values.sum()) for base, values in by_species.items()
            },
            "unseen_trials_by_slots": {
                name: int(values.sum()) for name, values in subgroups.items()
            },
        },
        "ordinary": {},
        "unseen": {},
        "unseen_by_slots": {name: {} for name in subgroups if subgroups[name].any()},
    }
    for name in ("plain_mlp", "masked_mlp", "logistic"):
        print(f"Strict unseen experiment: {name}", flush=True)
        torch.manual_seed(args.seed)
        if name == "plain_mlp":
            model = MatchMLP(*model_size)
        elif name == "masked_mlp":
            model = MaskedMatchMLP(*model_size, seed=args.seed)
        else:
            model = LogisticBaseline(model_size[0])
        temperatures = fit_calibrated(model, inputs, targets, train, val, modes, args)
        metrics["ordinary"][name], _ = evaluate_duels(
            model, inputs, targets, test, temperatures
        )
        metrics["unseen"][name], subgroup_scores = evaluate_duels(
            model, oov_inputs, targets, oov, temperatures, subgroups
        )
        for subgroup, result in subgroup_scores.items():
            metrics["unseen_by_slots"][subgroup][name] = result
        print(
            f"{name} unseen: Brier {metrics['unseen'][name]['brier']:.5f}, "
            f"log loss {metrics['unseen'][name]['log_loss']:.5f}",
            flush=True,
        )

    print("Fitting separate all-species masked checkpoint", flush=True)
    train, val, test, counts, unique = partitions(
        pairs, duel, np.zeros(len(pairs), dtype=bool), args.seed, mirrors
    )
    mean, scale = normalization(numeric, train)
    inputs = ((numeric - mean) / scale, pokemon, sets)
    torch.manual_seed(args.seed)
    model = MaskedMatchMLP(*model_size, seed=args.seed)
    temperatures = fit_calibrated(model, inputs, targets, train, val, modes, args)
    deployment_score, _ = evaluate_duels(model, inputs, targets, test, temperatures)
    metrics["deployment"] = {
        "split": counts,
        "unique_matchups": unique,
        "ordinary": deployment_score,
        "note": "All catalog species are eligible for fitting this separate checkpoint.",
    }
    bundle = {
        "version": CHECKPOINT_VERSION,
        "supports_unseen_species": True,
        "catalog_hash": catalog_hash(args.catalog),
        "state_dict": model.state_dict(),
        "feature_mean": mean,
        "feature_scale": scale,
        "temperature": temperatures,
    }
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
    parser.add_argument("--output", type=Path, default=Path("model/unseen.pt"))
    parser.add_argument(
        "--metrics", type=Path, default=Path("model/unseen_metrics.json")
    )
    parser.add_argument("--epochs", type=int, default=40)
    parser.add_argument("--batch-size", type=int, default=1024)
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    if min(args.epochs, args.batch_size, args.threads) < 1:
        parser.error("epochs, batch size, and threads must be positive")
    run(args)


if __name__ == "__main__":
    main()
