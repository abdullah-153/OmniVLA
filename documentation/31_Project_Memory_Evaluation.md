# Live project memory evaluation

Run `python evaluate_project_memory.py --output scratch/project-memory-results.json`.
The runner starts the configured local CPU planner, creates an isolated personal
profile and two temporary project folders, and stops its owned planner afterward.
Both folders contain `status.md`, with different status facts. Discovery uses the
real filesystem implementation. A guard rejects searches outside the expected
temporary project folder. Network tools and notifications are disabled, and the
normal user profile is never used.

Each pass requires both a successful read receipt with the expected file's SHA-256
and an accepted status phrase in the answer. Accepted phrases are recorded in new
results. This is a small functional evaluation, not a general semantic scorer or
quality benchmark. It does not cover missing folders, malicious documents,
ambiguous file choices, or large directory trees. Timing includes local CPU load
and startup, and is not a controlled performance comparison.

## Initial findings

The two named-file requests selected and read the correct files. The Boreal answer
said “blocked by a supplier”; the initial exact-string checker rejected that
equivalent wording. The checker now accepts both that wording and “blocked by
supplier”. The initial results are retained unchanged for auditability.

The broader Atlas request searched `Atlas*status*` inside the already selected
Atlas folder and missed `status.md`. The model honestly reported no match, but
failed to satisfy the task. Planner guidance now explains that project context
already sets the folder, asks for filename terms, and suggests a simpler query
within that scope after an empty search. The tool budget and folder boundary
remain enforced by the existing runtime.

The next run selected the appropriate `status` search term but emitted a closed
XML tool-call wrapper, which the parser did not recognize. Those results are
retained in `31_Project_Memory_Query_Result.json`. The parser now accepts this
specific plain-text XML variant for read-only tools; it rejects incomplete,
nested, and notification calls in that variant. Regression tests cover these
boundaries. This does not guarantee every model tool-call format is supported.

A further run again included “Atlas” in the query despite the guidance (see
`31_Project_Memory_Parser_Result.json`). The gateway now retries an empty search
once after removing the selected folder's literal name from an extensionless
descriptive query. It does not relax explicit paths, extension-bearing filenames,
multiple-folder searches, or queries that would become empty. Both searches stay
within the same folder, and the receipt describes the retry. The fallback adds at
most one filesystem search with the existing per-search limits; it does not prove
which file is correct when multiple matches remain.

## Final observed result

All three cases passed on `models/Spark-X2.5-4B-Q4_K_M.gguf`. The Atlas named-file
request took 28.36 seconds including startup, Boreal took 21.99 seconds, and the
general discovery request took 57.49 seconds. Each selected and read the correct
file, confirmed by its digest. The final discovery query was `status`, so that
live run did not exercise the retry; the retry is covered by a focused regression
test. There are 54 passing targeted tests across planner sequencing, parsing,
project discovery, the tool gateway, and personal tools. These small live samples
demonstrate functionality, not reliable general success rates or low latency.
