"""Validate 1:1 win probabilities against repeated, held-out Showdown battles."""

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import math
from pathlib import Path
import subprocess
from tempfile import NamedTemporaryFile

import torch

from .model import Predictor


ROOT = Path(__file__).resolve().parents[1]
CHECKPOINT = ROOT / "model" / "model.pt"
METRICS = ROOT / "model" / "metrics.json"
CATALOG = ROOT / "data" / "catalog.json"
SCENARIO_SEED = 20261202
BATCHES = ((0, 20261203), (25, 20261204), (50, 20261205), (75, 20261206))
CASES_PER_BATCH = 25
TRIALS_PER_CASE = 300


def simulate_batch(batch):
    offset, battle_seed = batch
    command = [
        "node",
        "sim/compare.mjs",
        "--test-split",
        str(METRICS),
        "--case-seed",
        str(SCENARIO_SEED),
        "--case-offset",
        str(offset),
        "--case-count",
        str(CASES_PER_BATCH),
        "--seed",
        str(battle_seed),
        "--trials",
        str(TRIALS_PER_CASE),
    ]
    result = subprocess.run(
        command, cwd=ROOT, stdout=subprocess.PIPE, encoding="utf-8", check=True
    )
    return json.loads(result.stdout)


def make_report(batches):
    torch.set_num_threads(1)
    model = Predictor.load(CHECKPOINT, CATALOG)
    metrics = json.loads(METRICS.read_text(encoding="utf-8"))
    test_pairings = set(metrics["data"]["matchup_partitions"]["test"])
    rows = []
    for batch in batches:
        for case in batch["cases"]:
            if case["id"] not in test_pairings:
                raise ValueError(f"Unexpected matchup outside test split: {case['id']}")
            observed = case["results"][0]
            predicted = model.predict(case["scenario"], ["auto"])[0]
            rows.append(
                {
                    "pair": case["id"],
                    "scenario": case["scenario"],
                    "trials": observed["n"],
                    "sim_win_rate": observed["win_rate"],
                    "sim_standard_error": observed["standard_error"],
                    "model_win_rate": predicted["win"],
                }
            )
    expected_cases = CASES_PER_BATCH * len(BATCHES)
    unique_pairings = {case["pair"] for case in rows}
    total_battles = sum(case["trials"] for case in rows)
    if len(unique_pairings) != len(rows) or len(rows) != expected_cases:
        raise ValueError("Expected one scenario per held-out matchup.")
    if total_battles != expected_cases * TRIALS_PER_CASE:
        raise ValueError("A held-out simulation ended before producing all outcomes.")

    gaps = [case["model_win_rate"] - case["sim_win_rate"] for case in rows]
    close_gaps = [
        gap for case, gap in zip(rows, gaps)
        if 0.4 <= case["sim_win_rate"] <= 0.6
    ]
    return {
        "cases": len(rows),
        "battles": total_battles,
        "trials_per_case": TRIALS_PER_CASE,
        "engine": batches[0]["engine"],
        "format": batches[0]["format"],
        "model_sha256": hashlib.sha256(CHECKPOINT.read_bytes()).hexdigest(),
        "scenario_seed": SCENARIO_SEED,
        "battle_seeds": [seed for _, seed in BATCHES],
        "probability_mae": sum(map(abs, gaps)) / len(gaps),
        "probability_rmse": math.sqrt(sum(gap**2 for gap in gaps) / len(gaps)),
        "observed_40_60": {
            "cases": len(close_gaps),
            "probability_mae": sum(map(abs, close_gaps)) / len(close_gaps) if close_gaps else None,
        },
        "mean_simulation_standard_error": sum(
            case["sim_standard_error"] for case in rows
        )
        / len(rows),
        "scope_ko": (
            "Showdown 행동 정책과 대표 세트의 추정 사용률을 기준으로 반복한 결과입니다. "
            "입력한 HP 비율을 엔진의 정수 HP로 환산하고, 상태이상 면역은 엔진 규칙을 따릅니다."
        ),
        "rows": rows,
    }


def write_report(report, output):
    output.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=output.parent, delete=False
    ) as stream:
        temporary = Path(stream.name)
        json.dump(report, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    temporary.replace(output)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "model" / "holdout.json")
    args = parser.parse_args()
    with ThreadPoolExecutor(max_workers=len(BATCHES)) as executor:
        results = list(executor.map(simulate_batch, BATCHES))
    report = make_report(results)
    write_report(report, args.output)
    print(f"{report['cases']} held-out cases · {report['battles']:,} completed battles")
    print(f"Probability MAE: {100 * report['probability_mae']:.2f} percentage points")


if __name__ == "__main__":
    main()
