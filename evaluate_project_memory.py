"""Opt-in live planner evaluation of remembered folders and real file discovery."""
import argparse
import hashlib
import json
from pathlib import Path
import tempfile
import time
from unittest.mock import patch

from cogniagent.gui import server_manager as planner
from cogniagent.memory.user_profile import UserProfileMemory
from cogniagent.tools.file_search import find_local_files
from cogniagent.tools.local_text_search import search_local_text


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    results = []
    with tempfile.TemporaryDirectory(prefix="omnivla-project-eval-") as directory:
        root = Path(directory)
        profile = UserProfileMemory(str(root / "memory"))
        reports = {}
        for project, status in [("Atlas", "awaiting review"), ("Boreal", "blocked by supplier")]:
            folder = root / project
            folder.mkdir()
            report = folder / "status.md"
            report.write_text(f"{project} status: {status}.", encoding="utf-8")
            reports[project] = report
            profile.link_entities("project", project, "stored_in", "folder", str(folder),
                                  source=f"The {project} project folder is {folder}")
        cases = [
            ("atlas_named_report", "Summarize status.md for the Atlas project.", "Atlas", ["awaiting review"]),
            ("boreal_named_report", "Summarize status.md for the Boreal project.", "Boreal", ["blocked by supplier", "blocked by a supplier"]),
            ("atlas_discovery", "Find the Atlas project status document and read it to tell me its status.", "Atlas", ["awaiting review"]),
            ("atlas_content_search", "Search the Atlas project file contents for status and tell me what they say.", "Atlas", ["awaiting review"]),
        ]
        try:
            for case_id, prompt, project, expected in cases:
                receipts, searches = [], []

                def discover(pattern, search_roots=None, **kwargs):
                    # Fail closed: an evaluation must never search the user's files.
                    if search_roots != [str(reports[project].parent)]:
                        raise ValueError("Expected the task's remembered project folder")
                    matches = find_local_files(pattern, search_roots=search_roots, **kwargs)
                    searches.append({"pattern": pattern, "project": project,
                                     "matches": [Path(item["path"]).name for item in matches]})
                    return matches

                started = time.monotonic()
                def search_contents(query, roots, **kwargs):
                    if roots != [str(reports[project].parent)]:
                        raise ValueError("Expected the task's remembered project folder")
                    result = search_local_text(query, roots, **kwargs)
                    searches.append({"query": query, "project": project, "kind": "content",
                                     "matches": [Path(item["path"]).name for item in result.get("matches", [])]})
                    return result
                try:
                    with patch("cogniagent.memory.user_profile.get_user_profile", return_value=profile), \
                         patch.object(planner, "find_local_files", side_effect=discover), \
                         patch.object(planner, "search_local_text", side_effect=search_contents), \
                         patch.object(planner, "execute_browser_search", return_value="Disabled in evaluation."), \
                         patch.object(planner, "read_webpage", return_value={"success": False}), \
                         patch.object(planner, "send_notification", return_value=False):
                        answer = planner.run_planner_chat(prompt, [], temp=0, max_tokens=384,
                            learn_personal_context_enabled=False, persist_in_ram=True,
                            tool_result_callback=receipts.append)
                    expected_hash = hashlib.sha256(reports[project].read_bytes()).hexdigest()
                    grounded = any(r.name in {"READ_LOCAL_FILE", "SEARCH_LOCAL_TEXT"} and r.ok and
                                   r.artifact_sha256 == expected_hash for r in receipts)
                    result = {"id": case_id, "answer": answer, "searches": searches,
                              "tools": [{"name": r.name, "ok": r.ok} for r in receipts],
                              "read_expected_file": grounded,
                              "accepted_phrases": expected,
                              "passed": (grounded and any(phrase.casefold() in answer.casefold() for phrase in expected)
                                         and (case_id != "atlas_content_search" or any(r.name == "SEARCH_LOCAL_TEXT" for r in receipts)))}
                except Exception as error:
                    result = {"id": case_id, "passed": False, "error": str(error), "searches": searches}
                result["duration_seconds"] = round(time.monotonic() - started, 2)
                results.append(result)
                args.output.parent.mkdir(parents=True, exist_ok=True)
                args.output.write_text(json.dumps({"model": str(planner.config.llm.planner_model),
                    "scope": "Real planner, isolated memory and real temporary files; external effects disabled.",
                    "cases": results}, indent=2), encoding="utf-8")
                print(json.dumps(result), flush=True)
        finally:
            planner.stop_planner_server()
    return 0 if all(result["passed"] for result in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
