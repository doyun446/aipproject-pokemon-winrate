"""Portable PyTorch model and prediction API."""

import hashlib
import itertools
import json
from pathlib import Path

import numpy as np
import torch
from torch import nn

from .catalog import ACTIONS, Catalog, showdown_id, swap_sides
from .features import Encoder


CHECKPOINT_VERSION = 2


def catalog_hash(path):
    data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    canonical = json.dumps(
        data, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class MatchMLP(nn.Module):
    def __init__(self, feature_count, pokemon_count, set_count):
        super().__init__()
        self.pokemon_embedding = nn.Embedding(pokemon_count + 1, 10, padding_idx=0)
        self.set_embedding = nn.Embedding(set_count + 1, 6, padding_idx=0)
        self.shared = nn.Sequential(
            nn.Linear(feature_count + 6 * 16, 128),
            nn.LayerNorm(128),
            nn.SiLU(),
            nn.Dropout(0.10),
            nn.Linear(128, 64),
            nn.SiLU(),
        )
        self.win = nn.Linear(64, 1)
        self.hp = nn.Linear(64, 1)

    def forward(self, features, pokemon, sets):
        embedded = torch.cat(
            (
                features,
                self.pokemon_embedding(pokemon).flatten(start_dim=1),
                self.set_embedding(sets).flatten(start_dim=1),
            ),
            dim=1,
        )
        representation = self.shared(embedded)
        return self.win(representation).squeeze(1), self.hp(representation).squeeze(1)


class LogisticBaseline(nn.Module):
    """Regularized logistic regression over the numeric battle-state features."""

    def __init__(self, feature_count):
        super().__init__()
        self.linear = nn.Linear(feature_count, 1)

    def forward(self, features, pokemon, sets):
        return self.linear(features).squeeze(1), None


class Predictor:
    def __init__(
        self,
        catalog,
        model,
        feature_mean,
        feature_scale,
        temperature,
        *,
        duel_only=False,
    ):
        self.catalog = catalog
        self.encoder = Encoder(catalog)
        self.model = model.eval()
        self.feature_mean = feature_mean
        self.feature_scale = feature_scale
        self.temperature = temperature
        self.duel_only = duel_only

    @classmethod
    def load(cls, model_path, catalog_path, fallback_catalog_path=None):
        bundle = torch.load(model_path, map_location="cpu", weights_only=True)
        if bundle["version"] != CHECKPOINT_VERSION:
            raise ValueError(
                "This checkpoint uses an unsupported schema. Retrain with the current code."
            )
        supports_unseen = bundle.get("supports_unseen_species", False)
        if fallback_catalog_path is not None and not supports_unseen:
            raise ValueError(
                "Use a checkpoint trained for unseen species with the fallback catalog."
            )
        catalog = Catalog(catalog_path, fallback_catalog_path)
        if catalog_hash(catalog.path) != bundle["catalog_hash"]:
            raise ValueError(
                "The checkpoint and catalog do not match. Use the original catalog or retrain."
            )
        mean = bundle["feature_mean"]
        model = MatchMLP(len(mean), len(catalog.pokemon_ids), len(catalog.set_ids))
        model.load_state_dict(bundle["state_dict"])
        return cls(
            catalog,
            model,
            mean,
            bundle["feature_scale"],
            bundle["temperature"],
            duel_only=supports_unseen,
        )

    def opponent_sets(self, scenario):
        probabilities = {}
        for variants, weight in self._weighted_teams(scenario["foe"]):
            set_id = variants[0]["id"]
            probabilities[set_id] = probabilities.get(set_id, 0.0) + weight
        return sorted(
            (
                {
                    **self.catalog.sets[(scenario["foe"][0]["pokemon"], set_id)],
                    "probability": probability,
                }
                for set_id, probability in probabilities.items()
            ),
            key=lambda set_data: set_data["probability"],
            reverse=True,
        )

    @staticmethod
    def _distinct_items(team):
        items = [set_data["item"] for set_data in team if set_data.get("item")]
        return len(items) == len(set(items))

    def _check_roster(self, roster):
        if not 1 <= len(roster) <= 3:
            raise ValueError("A roster must contain between one and three Pokémon.")
        species = [self.catalog.pokemon[slot["pokemon"]] for slot in roster]
        base_species = {entry.get("base_species", entry["id"]) for entry in species}
        if (
            len(base_species) != len(roster)
            or sum(bool(entry.get("mega")) for entry in species) > 1
        ):
            raise ValueError(
                "A roster requires distinct species and at most one Mega Pokémon."
            )

    def _weighted_teams(self, roster):
        self._check_roster(roster)
        choices = [self.catalog.compatible_sets(slot) for slot in roster]
        teams = []
        for completion in itertools.product(*choices):
            variants, weights = zip(*completion)
            if self._distinct_items(variants):
                teams.append((variants, float(np.prod(weights))))
        if not teams:
            raise ValueError(
                "No legal opponent set combination has distinct held items."
            )
        total = sum(weight for _, weight in teams)
        return [(variants, weight / total) for variants, weight in teams]

    def _completions(self, scenario):
        self._check_roster(scenario["own"])
        own_sets = [(slot["pokemon"], slot.get("set")) for slot in scenario["own"]]
        if not all(key in self.catalog.sets for key in own_sets):
            raise ValueError(
                "Each Pokémon on your side needs a known set from the catalog."
            )
        if not self._distinct_items([self.catalog.sets[key] for key in own_sets]):
            raise ValueError("Your team's held items must be distinct.")
        for variants, weight in self._weighted_teams(scenario["foe"]):
            foe = [
                {**slot, "set": set_data["id"]}
                for slot, set_data in zip(scenario["foe"], variants)
            ]
            yield {**scenario, "foe": foe}, weight

    def legal_actions(self, scenario):
        if scenario["mode"] == "duel":
            return ["auto"]
        if self.duel_only:
            raise ValueError("The unseen-species predictor supports 1:1 battles only.")
        own, foe = scenario["own"][0], scenario["foe"][0]
        own_key = (own["pokemon"], own["set"])
        own_set = self.catalog.sets[own_key]
        own_ability = showdown_id(
            own_set.get("battle_ability") or own_set.get("ability")
        )
        immune_to_shadow_tag = (
            "Ghost" in self.encoder.types[own_key]
            or own_ability in ("shadowtag", "neutralizinggas")
            or showdown_id(own_set.get("item")) == "shedshell"
        )
        trapped = not immune_to_shadow_tag and all(
            showdown_id(candidate.get("battle_ability") or candidate.get("ability"))
            == "shadowtag"
            for candidate, _ in self.catalog.compatible_sets(foe)
        )
        switch_count = 0 if trapped else len(scenario["own"]) - 1
        return [*ACTIONS[1:5], *ACTIONS[5 : 5 + switch_count]]

    @torch.inference_mode()
    def predict(self, scenario, actions):
        """Return the posterior win probability, candidate-set range, and expected HP."""
        actions = list(actions)
        if not actions:
            return []
        legal_actions = self.legal_actions(scenario)
        if not all(action in legal_actions for action in actions):
            raise ValueError(
                "Requested action is unavailable in the current battle state."
            )
        samples = list(self._completions(scenario))
        encoded = [
            self.encoder.encode(state, action)
            for state, _ in samples
            for action in actions
        ]
        size = len(encoded)
        if scenario["mode"] == "duel":
            encoded.extend(
                self.encoder.encode(swap_sides(state), "auto") for state, _ in samples
            )
        state_features, pokemon, sets = zip(*encoded)
        features = torch.from_numpy(np.stack(state_features))
        logits, hp_logits = self.model(
            (features - self.feature_mean) / self.feature_scale,
            torch.tensor(pokemon, dtype=torch.long),
            torch.tensor(sets, dtype=torch.long),
        )
        probs = torch.sigmoid(logits / self.temperature[scenario["mode"]])
        if scenario["mode"] == "duel":
            probs = (probs[:size] + 1 - probs[size:]) * 0.5
        weights = torch.tensor([weight for _, weight in samples], dtype=probs.dtype)
        by_set = probs.reshape(len(samples), len(actions))
        wins = (weights @ by_set).clamp(0, 1)
        health = (
            weights
            @ torch.sigmoid(hp_logits[:size]).reshape(len(samples), len(actions))
        ).clamp(0, 1)
        return [
            {
                "action": action,
                "win": float(win),
                "set_min": float(lower),
                "set_max": float(upper),
                "hp_after": float(hp) * 100,
            }
            for action, win, lower, upper, hp in zip(
                actions, wins, by_set.amin(dim=0), by_set.amax(dim=0), health
            )
        ]
