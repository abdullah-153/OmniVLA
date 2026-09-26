# Skill run outcomes

Desktop execution fingerprints the selected skill's Markdown at selection time. Completed agent loops record the fingerprint, run identifier, success flag, duration, number of recorded inputs, and verification source in `skills/.outcomes.sqlite3`. Duplicate run identifiers do not count twice. No task text, typed content, or screenshot is included.

Authenticated skill detail responses include up to 30 per-version summaries: run count, successful runs, average duration, and last run time. The fingerprint represents the selected Markdown guidance; it can differ from an archived raw JSON source digest.

These are observational metrics, not controlled benchmarks or evidence that a skill caused success. Hard process termination before the loop returns does not produce a record. Outcomes currently inform inspection only; they do not automatically grant execution permission or promote a skill. A visible outcome panel and controlled evaluation cases remain future work.
