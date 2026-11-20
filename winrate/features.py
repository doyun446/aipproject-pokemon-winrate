"""Encode only information available before the first action of a matchup."""

from functools import lru_cache
from math import ceil, log

import numpy as np

from .catalog import ACTIONS, STATUSES, WEATHERS, showdown_id, target_index


# Attack type -> (super-effective, resisted, immune) defending types.
TYPE_CHART = {
    "Normal": ((), ("Rock", "Steel"), ("Ghost",)),
    "Fire": (("Grass", "Ice", "Bug", "Steel"), ("Fire", "Water", "Rock", "Dragon"), ()),
    "Water": (("Fire", "Ground", "Rock"), ("Water", "Grass", "Dragon"), ()),
    "Electric": (("Water", "Flying"), ("Electric", "Grass", "Dragon"), ("Ground",)),
    "Grass": (
        ("Water", "Ground", "Rock"),
        ("Fire", "Grass", "Poison", "Flying", "Bug", "Dragon", "Steel"),
        (),
    ),
    "Ice": (
        ("Grass", "Ground", "Flying", "Dragon"),
        ("Fire", "Water", "Ice", "Steel"),
        (),
    ),
    "Fighting": (
        ("Normal", "Ice", "Rock", "Dark", "Steel"),
        ("Poison", "Flying", "Psychic", "Bug", "Fairy"),
        ("Ghost",),
    ),
    "Poison": (("Grass", "Fairy"), ("Poison", "Ground", "Rock", "Ghost"), ("Steel",)),
    "Ground": (
        ("Fire", "Electric", "Poison", "Rock", "Steel"),
        ("Grass", "Bug"),
        ("Flying",),
    ),
    "Flying": (("Grass", "Fighting", "Bug"), ("Electric", "Rock", "Steel"), ()),
    "Psychic": (("Fighting", "Poison"), ("Psychic", "Steel"), ("Dark",)),
    "Bug": (
        ("Grass", "Psychic", "Dark"),
        ("Fire", "Fighting", "Poison", "Flying", "Ghost", "Steel", "Fairy"),
        (),
    ),
    "Rock": (("Fire", "Ice", "Flying", "Bug"), ("Fighting", "Ground", "Steel"), ()),
    "Ghost": (("Psychic", "Ghost"), ("Dark",), ("Normal",)),
    "Dragon": (("Dragon",), ("Steel",), ("Fairy",)),
    "Dark": (("Psychic", "Ghost"), ("Fighting", "Dark", "Fairy"), ()),
    "Steel": (("Ice", "Rock", "Fairy"), ("Fire", "Water", "Electric", "Steel"), ()),
    "Fairy": (("Fighting", "Dragon", "Dark"), ("Fire", "Poison", "Steel"), ()),
}
STAT_KEYS = ("hp", "atk", "def", "spa", "spd", "spe")
NATURE_STATS = {
    name: (raised, lowered)
    for raised, row in (
        ("atk", ("Hardy", "Lonely", "Adamant", "Naughty", "Brave")),
        ("def", ("Bold", "Docile", "Impish", "Lax", "Relaxed")),
        ("spa", ("Modest", "Mild", "Bashful", "Rash", "Quiet")),
        ("spd", ("Calm", "Gentle", "Careful", "Quirky", "Sassy")),
        ("spe", ("Timid", "Hasty", "Jolly", "Naive", "Serious")),
    )
    for lowered, name in zip(STAT_KEYS[1:], row)
}
WEATHER_DAMAGE = {
    ("rain", "Water"): 1.5,
    ("rain", "Fire"): 0.5,
    ("sun", "Fire"): 1.5,
    ("sun", "Water"): 0.5,
}


def _type_multiplier(move_type, defending_types):
    weak, resist, immune = TYPE_CHART.get(move_type, ((), (), ()))
    if any(element in immune for element in defending_types):
        return 0.0
    return 2.0 ** (
        sum(element in weak for element in defending_types)
        - sum(element in resist for element in defending_types)
    )


def _stage(value):
    return (2 + max(value, 0)) / (2 + max(-value, 0))


def _one_hot(value, options):
    return [float(value == option) for option in options]


class Encoder:
    def __init__(self, catalog):
        self.catalog = catalog
        self.base_stats = {}
        self.types = {}
        self.stat_points = {}
        self.nature = {}
        for key, set_data in catalog.sets.items():
            mon = catalog.pokemon[key[0]]
            base_stats = (
                set_data.get("battle_base_stats") or mon.get("base_stats") or {}
            )
            points = set_data.get("evs") or {}
            raised, lowered = NATURE_STATS.get(
                str(set_data.get("nature", "")).title(), (None, None)
            )
            self.stat_points[key] = tuple(
                int(points.get(stat, 0)) for stat in STAT_KEYS
            )
            self.nature[key] = tuple(
                110
                if stat == raised and raised != lowered
                else 90
                if stat == lowered and raised != lowered
                else 100
                for stat in STAT_KEYS
            )
            self.base_stats[key] = tuple(int(base_stats[stat]) for stat in STAT_KEYS)
            self.types[key] = tuple(
                str(t).title() for t in (set_data.get("battle_types") or mon["types"])
            )

    @staticmethod
    def _key(slot):
        return (slot["pokemon"], slot["set"])

    def _variant(self, slot):
        key = self._key(slot)
        overrides = slot.get("evs")
        if not overrides:
            return key, None
        if not set(overrides).issubset(STAT_KEYS):
            raise ValueError("Unrecognized stat in Stat Point allocation.")
        points = tuple(
            overrides.get(stat, baseline)
            for stat, baseline in zip(STAT_KEYS, self.stat_points[key])
        )
        if (
            not all(isinstance(value, int) and 0 <= value <= 32 for value in points)
            or sum(points) > 66
        ):
            raise ValueError(
                "Stat Points must be integers from 0 to 32, with at most 66 total."
            )
        return key, points

    @lru_cache(maxsize=20_000)
    def _variant_stats(self, variant):
        key, points = variant
        points = self.stat_points[key] if points is None else points
        return {
            # Showdown Champions Reg M-C uses fixed level-50 stats.
            stat: base + point + 75
            if stat == "hp"
            else (base + point + 20) * nature // 100
            for stat, base, point, nature in zip(
                STAT_KEYS, self.base_stats[key], points, self.nature[key]
            )
        }

    def _slot(self, slot):
        if slot is None:
            return [0.0] * 17
        status = slot.get("status") or ""
        if status not in STATUSES:
            raise ValueError(f"Unsupported Pokémon status: {status!r}")
        hp = float(slot["hp"])
        attack = int(slot.get("attack", 0))
        speed = int(slot.get("speed", 0))
        if not (0 <= hp <= 100 and -6 <= attack <= 6 and -6 <= speed <= 6):
            raise ValueError(
                "HP must be in [0, 100] and stat stages must be in [-6, 6]."
            )
        stats = self._variant_stats(self._variant(slot))
        return [
            1.0,
            hp / 100,
            attack / 6,
            speed / 6,
            *_one_hot(status, STATUSES),
            *(stats[key] / 220 for key in STAT_KEYS),
        ]

    @lru_cache(maxsize=50_000)
    def _base_pressure(self, attacker, defender, weather):
        stats = self._variant_stats(attacker)
        defenses = self._variant_stats(defender)
        attacker_key, defender_key = attacker[0], defender[0]
        moves = self.catalog.sets[attacker_key]["moves"]
        pressures = []
        for name in moves:
            move = self.catalog.moves.get(showdown_id(name), {})
            element = str(move.get("type", "")).title()
            category = str(move.get("category", "Status")).lower()
            power = float(move.get("base_power") or 0)
            accuracy = move.get("accuracy", 100)
            accuracy = 1.0 if accuracy is True else float(accuracy or 0) / 100
            effectiveness = _type_multiplier(element, self.types[defender_key])
            physical = category == "physical"
            utility = category == "status"
            ratio = (
                stats["atk"] / defenses["def"]
                if physical
                else stats["spa"] / defenses["spd"]
            )
            stab = 1.5 if element in self.types[attacker_key] else 1.0
            damage = (
                power
                / 100
                * ratio
                * effectiveness
                * stab
                * WEATHER_DAMAGE.get((weather, element), 1.0)
            )
            pressures.append(
                (
                    damage,
                    accuracy,
                    physical,
                    utility,
                    float(move.get("priority") or 0),
                    effectiveness,
                )
            )
        return pressures

    def _moves(self, attacker, defender, weather, *, entering=False):
        stage = _stage(0 if entering else int(attacker.get("attack", 0)))
        if attacker.get("status") == "brn":
            stage *= 0.5
        return [
            (
                damage * (stage if physical else 1),
                accuracy,
                float(physical),
                float(utility),
                priority,
                effectiveness,
            )
            for damage, accuracy, physical, utility, priority, effectiveness in self._base_pressure(
                self._variant(attacker), self._variant(defender), weather
            )
        ]

    def _speed(self, slot, entering=False):
        speed = self._variant_stats(self._variant(slot))["spe"] * _stage(
            0 if entering else int(slot.get("speed", 0))
        )
        return speed / 2 if slot.get("status") == "par" else speed

    def _damage_fraction(self, pressure, target):
        max_hp = self._variant_stats(self._variant(target))["hp"]
        remaining_hp = max(max_hp * float(target["hp"]) / 100, 1)
        # At level 50, the leading coefficient in the damage formula is 22/50.
        # Pressure already includes power/100, approximate modifiers and accuracy.
        return min(44 * pressure / remaining_hp, 4.0)

    @staticmethod
    def _ko_turns(damage_fraction):
        return min(8, ceil(1 / damage_fraction)) / 8 if damage_fraction else 1.0

    def _pair(self, own, foe, weather, *, entering=False):
        if own is None or foe is None:
            return [0.0] * 7
        own_best = max(
            (m[0] * m[1] for m in self._moves(own, foe, weather, entering=entering)),
            default=0,
        )
        foe_best = max((m[0] * m[1] for m in self._moves(foe, own, weather)), default=0)
        speed_delta = self._speed(own, entering) - self._speed(foe)
        own_fraction = self._damage_fraction(own_best, foe)
        foe_fraction = self._damage_fraction(foe_best, own)
        return [
            own_best,
            foe_best,
            speed_delta / 150,
            own_fraction,
            foe_fraction,
            self._ko_turns(own_fraction),
            self._ko_turns(foe_fraction),
        ]

    def damage_rule_logit(self, scenario):
        """Baseline for duels: compare approximate damage per turn against remaining HP."""
        own, foe = scenario["own"][0], scenario["foe"][0]
        _, _, speed, own_fraction, foe_fraction, _, _ = self._pair(
            own, foe, scenario.get("weather") or ""
        )
        return log((0.05 + own_fraction) / (0.05 + foe_fraction)) + 0.4 * speed

    def encode(self, scenario, action):
        mode = scenario["mode"]
        own = scenario["own"]
        foe = scenario["foe"]
        weather = scenario.get("weather") or ""
        if mode not in ("duel", "team") or weather not in WEATHERS:
            raise ValueError(f"Unsupported mode or weather: {mode!r}, {weather!r}")
        size = 1 if mode == "duel" else 3
        if not (1 <= len(own) <= size and 1 <= len(foe) <= size):
            raise ValueError(f"Invalid team sizes for {mode}.")
        is_switch = action.startswith("switch:")
        if (
            action not in ACTIONS
            or (mode == "duel") != (action == "auto")
            or target_index(action) >= len(own)
        ):
            raise ValueError(
                f"Action {action!r} is unavailable in the current scenario."
            )

        slots = [*own, *([None] * (3 - len(own))), *foe, *([None] * (3 - len(foe)))]
        mon_ids = [
            self.catalog.pokemon_ids.get(slot["pokemon"], 0) if slot else 0
            for slot in slots
        ]
        set_ids = [
            self.catalog.set_ids.get(self._key(slot), 0) if slot else 0
            for slot in slots
        ]
        slot_features = [value for slot in slots for value in self._slot(slot)]
        pairs = [
            self._pair(slot, foe[0], weather, entering=i > 0)
            for i, slot in enumerate(slots[:3])
        ]
        pairs.extend(self._pair(own[0], slot, weather) for slot in slots[4:])
        move_features = [0.0] * 6
        if action.startswith("move:"):
            move_index = int(action[-1])
            move_features = self._moves(own[0], foe[0], weather)[move_index]
        selected_pair = pairs[target_index(action)]
        encoded = np.asarray(
            [
                float(mode == "team"),
                float(is_switch),
                *_one_hot(weather, WEATHERS),
                *_one_hot(action, ACTIONS),
                *slot_features,
                *(value for pair in pairs for value in pair),
                *selected_pair,
                *move_features,
            ],
            dtype=np.float32,
        )
        return encoded, mon_ids, set_ids
