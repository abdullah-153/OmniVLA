"""Opt-in live local planner evaluation with synthetic, side-effect-free tools."""
import argparse
import json
from pathlib import Path
import tempfile
import time
from unittest.mock import patch

from cogniagent.gui import server_manager as planner


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    results = []
    with tempfile.TemporaryDirectory(prefix="omnivla-eval-") as directory:
        report = Path(directory) / "atlas.md"
        report.write_text("Atlas delivery date: 14 November. Status: awaiting review.", encoding="utf-8")
        cases = [
            ("read_named_report", "Summarize atlas.md", ["FIND_FILES", "READ_LOCAL_FILE"], "awaiting review"),
            ("discover_and_read", "Find the Atlas project status document and read it to tell me its delivery date.",
             ["FIND_FILES", "READ_LOCAL_FILE"], "14 November"),
        ]
        try:
            for case_id, prompt, expected_tools, expected_text in cases:
                receipts = []
                started = time.monotonic()
                try:
                    with patch.object(planner, "find_local_files", return_value=[{"name": report.name, "path": str(report)}]), \
                         patch.object(planner, "execute_browser_search", return_value="No web results in this evaluation."), \
                         patch.object(planner, "read_webpage", return_value={"success": False, "text": "Disabled for this evaluation."}), \
                         patch.object(planner, "send_notification", return_value=False):
                        answer = planner.run_planner_chat(prompt, [], temp=0, max_tokens=384,
                            user_profile_context="No personal defaults supplied for this evaluation.",
                            learn_personal_context_enabled=False, persist_in_ram=True,
                            tool_result_callback=receipts.append)
                    names = [receipt.name for receipt in receipts]
                    result = {"id": case_id, "tools": names, "answer": answer,
                              "passed": names == expected_tools and expected_text.casefold() in answer.casefold()}
                except Exception as error:
                    result = {"id": case_id, "passed": False, "error": str(error)}
                result["duration_seconds"] = round(time.monotonic() - started, 2)
                results.append(result)
                args.output.write_text(json.dumps({"model": str(planner.config.llm.planner_model),
                    "scope": "Real local planner; synthetic tools and temporary data, no desktop execution.",
                    "cases": results}, indent=2), encoding="utf-8")
                print(json.dumps(result), flush=True)
        finally:
            planner.stop_planner_server()
    return 0 if all(result["passed"] for result in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
