# Personal context receipts

The context shown under an answer now comes from a snapshot of the personal
context block present in the fitted request accepted by the planner server.
The server no longer rebuilds the memory list after inference, which could
previously show omitted facts or preferences changed during the request.

Receipts describe supplied preferences, facts, linked entities, workflows, and
conflicts. They preserve the values present in that request. Repeated references
across accepted tool-synthesis requests are deduplicated, with at most ten shown.
Rejected HTTP requests and personal context removed by token fitting produce no
receipt. A receipt establishes that context was supplied; it does not establish
that the model followed or relied on it.

Ordinary answers now show context details as well as desktop plans. New messages
carry a persisted verification flag and use “Personal context supplied to the
planner.” Older messages without request-level evidence use “Related personal
context.” Existing historical metadata is preserved rather than retroactively
claimed as verified. Tool-side folder selection is separate from prompt context
and continues to be described in tool results.

Validation: 90 targeted tests pass, covering omitted context, actual fitted
payloads, HTTP failures, source snapshots, incoming relations, scoped preferences,
conflicts, persistence, deduplication, and legacy flags. Tests mock model replies;
they do not measure whether personal context improves task success.

The hidden Electron smoke test also passed for verified and legacy labels under
ordinary answers, followed by the existing planning-stop, approval, and overlay
checks. A desktop screenshot was visually inspected; no renderer console errors
were reported. The isolated fixture was shut down afterward.
