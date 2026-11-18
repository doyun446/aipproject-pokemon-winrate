"""Catalog and public battle-state helpers shared by training and inference."""

import json
import math
from pathlib import Path


WEATHERS = ("", "rain", "sun", "sand", "snow")
STATUSES = ("", "brn", "par", "psn", "tox", "slp", "frz")
ACTIONS = ("auto", "move:0", "move:1", "move:2", "move:3", "switch:1", "switch:2")


def showdown_id(value):
    return "".join(
        char for char in str(value).lower() if char.isascii() and char.isalnum()
    )


def swap_sides(scenario):
    return {**scenario, "own": scenario["foe"], "foe": scenario["own"]}


def target_index(action):
    return int(action[-1]) if action.startswith("switch:") else 0


class Catalog:
    def __init__(self, path):
        self.path = Path(path)
        data = json.loads(self.path.read_text(encoding="utf-8-sig"))
        self.pokemon = {entry["id"]: entry for entry in data["pokemon"]}
        if not self.pokemon:
            raise ValueError("The catalog must contain at least one Pokémon.")
        self.sets = {
            (pokemon_id, set_data["id"]): set_data
            for pokemon_id, entry in self.pokemon.items()
            for set_data in entry["sets"]
        }
        self.pokemon_ids = {
            key: index for index, key in enumerate(sorted(self.pokemon), 1)
        }
        self.set_ids = {key: index for index, key in enumerate(sorted(self.sets), 1)}
        self.moves = {
            showdown_id(key): value for key, value in data.get("move_data", {}).items()
        }

    def compatible_sets(self, slot):
        candidates = self.pokemon[slot["pokemon"]]["sets"]
        known = slot.get("set")
        revealed_item = showdown_id(slot.get("revealed_item") or "")
        revealed_moves = {
            showdown_id(move) for move in slot.get("revealed_moves", ()) if move
        }
        weighted = []
        for set_data in candidates:
            if known and set_data["id"] != known:
                continue
            if (
                revealed_item
                and showdown_id(set_data.get("item") or "") != revealed_item
            ):
                continue
            if revealed_moves and not revealed_moves.issubset(
                map(showdown_id, set_data["moves"])
            ):
                continue
            weight = float(set_data.get("weight", 1))
            if not math.isfinite(weight) or weight < 0:
                raise ValueError(f"Invalid weight for set {set_data['id']}.")
            weighted.append((set_data, weight))
        if not weighted:
            raise ValueError(
                f"No catalog set is compatible with the revealed details for {slot['pokemon']}."
            )
        total = sum(weight for _, weight in weighted)
        if not total:
            return [(set_data, 1 / len(weighted)) for set_data, _ in weighted]
        return [(set_data, weight / total) for set_data, weight in weighted if weight]
