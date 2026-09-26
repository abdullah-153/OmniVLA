"""Opt-in live checks of scoped preferences, overrides, and conflict handling."""
import argparse
import json
import re
from pathlib import Path
import tempfile
import time
from unittest.mock import patch

from cogniagent.gui import server_manager as planner
from cogniagent.memory.user_profile import UserProfileMemory


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-tokens", type=int, default=640,
                        help="Response allowance; defaults to the desktop planner's 640-token cap.")
    args = parser.parse_args()
    results = []
    with tempfile.TemporaryDirectory(prefix="omnivla-preferences-eval-") as directory:
        profile = UserProfileMemory(directory)
        profile.update_preference("email", "service", "Outlook")
        profile.update_scoped_preference("Project Atlas", "email", "service", "Gmail")
        profile.update_scoped_preference("Project Apollo", "email", "service", "Outlook")
        original = profile.to_dict()
        cases = [
            ("global_default", "Which email service is my saved default? Answer with only the service name.", ["outlook"], ["gmail"]),
            ("project_default", "Which email service should I use for Project Atlas? Answer with only the service name.", ["gmail"], ["outlook"]),
            ("unrelated_project", "Which email service should I use for Project Orion? Answer with only the service name.", ["outlook"], ["gmail"]),
            ("current_override", "For this message, use Outlook for Project Atlas email instead of its saved default. Which service applies? Answer only the service name.", ["outlook"], ["gmail"]),
            ("conflicting_projects", "Which email service should I use to send one joint update for Project Atlas and Project Apollo?", ["gmail", "outlook", "?"], []),
        ]
        try:
            for case_id, prompt, required, forbidden in cases:
                receipts, tools = [], []
                started = time.monotonic()
                try:
                    with patch("cogniagent.memory.user_profile.get_user_profile", return_value=profile), \
                         patch.object(planner, "execute_browser_search", return_value="Disabled in evaluation."), \
                         patch.object(planner, "find_local_files", return_value=[]), \
                         patch.object(planner, "search_local_text", return_value={"success": False}), \
                         patch.object(planner, "read_webpage", return_value={"success": False}), \
                         patch.object(planner, "send_notification", return_value=False):
                        answer = planner.run_planner_chat(prompt, [], temp=0, max_tokens=args.max_tokens,
                            learn_personal_context_enabled=False, persist_in_ram=True,
                            context_receipt_callback=receipts.extend, tool_result_callback=tools.append)
                    lower = answer.casefold()
                    unchanged = profile.to_dict() == original
                    chooses_service = (case_id != "conflicting_projects" or (
                        re.search(r"(?:which|what)[^?]{0,90}(?:service|provider)[^?]{0,90}\?", lower)
                        and "both services" not in lower and "one for each" not in lower))
                    result = {"id": case_id, "answer": answer, "context_receipts": receipts,
                        "memory_unchanged": unchanged, "tool_calls": [item.name for item in tools],
                        "passed": (all(word in lower for word in required) and
                                   not any(word in lower for word in forbidden) and unchanged and not tools and bool(chooses_service))}
                except Exception as error:
                    result = {"id": case_id, "passed": False, "error": str(error)}
                result["duration_seconds"] = round(time.monotonic() - started, 2)
                results.append(result)
                args.output.parent.mkdir(parents=True, exist_ok=True)
                args.output.write_text(json.dumps({"model": str(planner.config.llm.planner_model),
                    "requested_output_tokens": args.max_tokens,
                    "scope": "Real local planner; isolated synthetic preferences; external tools disabled; lexical checks require answer review.",
                    "cases": results}, indent=2), encoding="utf-8")
                print(json.dumps(result), flush=True)
        finally:
            planner.stop_planner_server()
    return 0 if all(result["passed"] for result in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
