# Skill run outcomes

Desktop execution fingerprints the selected skill's exact saved source bytes. Completed agent loops record the fingerprint, run identifier, success flag, duration, number of recorded inputs, and verification source in `skills/.outcomes.sqlite3`. Duplicate run identifiers do not count twice. No task text, typed content, or screenshot is included.

Authenticated skill detail responses include the current source fingerprint and up to 30 per-version summaries: run count, successful runs, average duration, visual/operator/inconclusive verification counts, and last run time. Restoring imported JSON or Markdown preserves the exact earlier fingerprint.

These are observational metrics, not controlled benchmarks or evidence that a skill caused success. Hard process termination before the loop returns does not produce a record. Outcomes appear in Skill Studio for inspection only; they do not automatically grant execution permission or promote a skill. Controlled end-to-end evaluation remains future work.
