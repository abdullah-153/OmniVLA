# Live planner evaluation — 26 September 2026

Run `python evaluate_live_planner.py --output scratch/live-planner-evaluation.json` to exercise the real configured local planner with synthetic tools and a temporary Markdown report. This opt-in command starts the planner if needed and stops the process it owns afterward. It does not execute desktop actions, send notifications, or learn personal preferences.

Observed results on this workspace using `models/Spark-X2.5-4B-Q4_K_M.gguf` on the CPU planner profile:

| Case | Selected tools | Result | Duration |
| --- | --- | --- | --- |
| Summarize a named report | FIND_FILES → READ_LOCAL_FILE | Correct date and status | 42.60 seconds, including startup |
| Discover and read a project status document | FIND_FILES → READ_LOCAL_FILE | Correct delivery date | 40.02 seconds |

Both cases passed. The report contained a delivery date of 14 November and status awaiting review; both answers were grounded in that text. Receipts confirmed the file-read tool ran, rather than accepting an answer based only on the filename.

This is a two-case functional check, not a task-success benchmark. File discovery returns a fixed synthetic match regardless of search wording, so it does not measure search-query quality, real filesystem recall, ambiguity handling, or resistance to hostile document instructions. Network tools are stubbed. Latency is one observation per case and includes CPU inference; it is not a percentile measurement. Broader evaluations with realistic retrieval and desktop outcomes remain outstanding.

## Shorter prompt for retrieved evidence

After removing desktop-planning instructions from requests with upfront tool evidence, both cases passed again on the same model. The named-report case took 19.59 seconds, versus 42.60 in the earlier run. The discovery case, which retains the full planning prompt, took 40.31 seconds versus 40.02. These are sequential single observations, not a controlled latency benchmark; cache and machine load can affect the difference. The compact prompt retains grounding, missing-evidence, personal-context, and untrusted-data instructions.
