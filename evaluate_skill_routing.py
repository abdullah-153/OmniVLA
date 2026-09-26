"""Offline skill-selection evaluation; does not execute desktop actions."""
import argparse
import hashlib
import json
from pathlib import Path
import time

from cogniagent.skills.skill_registry import SkillRegistry


def evaluate(registry, cases):
    if not isinstance(cases, list) or not cases or len(cases) > 1000:
        raise ValueError("Provide between 1 and 1000 evaluation cases.")
    results = []
    for case in cases:
        if not isinstance(case, dict) or not isinstance(case.get("prompt"), str) or "expected_skill" not in case:
            raise ValueError("Each case needs prompt and expected_skill (a name or null).")
        expected = case["expected_skill"]
        if expected is not None and not registry.get_skill(expected):
            raise ValueError(f"Expected skill is not registered: {expected}")
        started = time.perf_counter()
        selected, parameters = registry.match_skill(case["prompt"])
        elapsed = (time.perf_counter() - started) * 1000
        actual = selected.name if selected else None
        expected_parameters = case.get("expected_parameters", {})
        if not isinstance(expected_parameters, dict):
            raise ValueError("expected_parameters must be an object.")
        passed = actual == expected and all(parameters.get(key) == value for key, value in expected_parameters.items())
        results.append({"id": str(case.get("id", len(results) + 1)), "expected_skill": expected,
                        "actual_skill": actual, "passed": passed, "elapsed_ms": round(elapsed, 3)})
    return {"scope": "Deterministic skill routing only; no task execution or model quality measured.",
            "versions": {skill.name: hashlib.sha256(skill.to_markdown().encode("utf-8")).hexdigest()
                         for skill in registry.list_skills()},
            "total": len(results), "passed": sum(row["passed"] for row in results),
            "false_selections": sum(row["expected_skill"] is None and row["actual_skill"] is not None for row in results),
            "cases": results}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("cases", type=Path, help="JSON array of labeled routing cases")
    parser.add_argument("--skills-dir", default="skills")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = evaluate(SkillRegistry(args.skills_dir), json.loads(args.cases.read_text(encoding="utf-8")))
    rendered = json.dumps(report, indent=2)
    if args.output:
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0 if report["passed"] == report["total"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
