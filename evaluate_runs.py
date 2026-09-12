"""Aggregate privacy-safe OmniVLA run metrics for model/profile comparisons."""

from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Any


def _distribution(values: list[int]) -> dict[str, int | None]:
    clean = sorted(max(0, int(value)) for value in values)
    if not clean:
        return {"count": 0, "median": None, "p95": None}
    middle = len(clean) // 2
    median = clean[middle] if len(clean) % 2 else int(round((clean[middle - 1] + clean[middle]) / 2))
    p95 = clean[max(0, math.ceil(len(clean) * 0.95) - 1)]
    return {"count": len(clean), "median": median, "p95": p95}


def _profile_key(metrics: dict[str, Any]) -> str:
    profile = metrics.get("profile") if isinstance(metrics.get("profile"), dict) else {}
    return " | ".join(
        str(profile.get(field) or "unknown") for field in ("engine", "vla", "planner")
    )


def _summarize(metrics_rows: list[dict[str, Any]]) -> dict[str, Any]:
    statuses: dict[str, int] = defaultdict(int)
    durations: list[int] = []
    steps: list[int] = []
    phase_medians: dict[str, list[int]] = defaultdict(list)
    for metrics in metrics_rows:
        statuses[str(metrics.get("status") or "unknown")] += 1
        if isinstance(metrics.get("duration_ms"), int):
            durations.append(metrics["duration_ms"])
        if isinstance(metrics.get("steps"), int):
            steps.append(metrics["steps"])
        phases = metrics.get("phases") if isinstance(metrics.get("phases"), dict) else {}
        for phase, values in phases.items():
            if isinstance(values, dict) and isinstance(values.get("median_ms"), int):
                phase_medians[str(phase)].append(values["median_ms"])

    completed = len(metrics_rows)
    successes = statuses.get("success", 0)
    return {
        "runs": completed,
        "statuses": dict(sorted(statuses.items())),
        "success_rate": round(successes / completed, 4) if completed else None,
        "duration_ms": _distribution(durations),
        "steps": _distribution(steps),
        "per_run_phase_median_ms": {
            phase: _distribution(values) for phase, values in sorted(phase_medians.items())
        },
    }


def evaluate_database(database: dict[str, Any]) -> dict[str, Any]:
    chats = database.get("chats") if isinstance(database, dict) else None
    rows = [
        chat["run_metrics"]
        for chat in chats or []
        if isinstance(chat, dict) and isinstance(chat.get("run_metrics"), dict)
    ]
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for metrics in rows:
        groups[_profile_key(metrics)].append(metrics)
    return {
        "privacy": "Only content-free run_metrics fields were analyzed; intents, chat text, and screenshots were ignored.",
        "overall": _summarize(rows),
        "profiles": {name: _summarize(group) for name, group in sorted(groups.items())},
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=Path("chats_db.json"), help="OmniVLA run database")
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    args = parser.parse_args()
    try:
        database = json.loads(args.input.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        parser.error(f"unable to read {args.input}: {error}")
    report = evaluate_database(database)
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        overall = report["overall"]
        print("OmniVLA measured-run evaluation")
        print(f"Runs: {overall['runs']}  Success rate: {overall['success_rate']}")
        print(f"Duration ms (median/p95): {overall['duration_ms']['median']} / {overall['duration_ms']['p95']}")
        for profile, summary in report["profiles"].items():
            print(f"  {profile}: {summary['runs']} runs, success={summary['success_rate']}")
    return 0 if report["overall"]["runs"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
