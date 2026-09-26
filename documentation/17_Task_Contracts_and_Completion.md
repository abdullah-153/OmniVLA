# Task contracts and completion evidence

Reviewed desktop plans can now include up to five explicit **Success Criteria** alongside the expected output and planner budget. Criteria survive plan normalization and are displayed in the review card. The planner is prompted to make them concrete and observable.

At the end of a run, the visual verifier checks a fresh screenshot against every criterion. A positive overall claim with a missing or failed criterion is rejected. If the model cannot provide complete criterion evidence, the outcome remains inconclusive and the operator is asked to confirm it explicitly. Legacy plans without criteria retain expected-output verification. The run result stores a compact completion check identifying whether the conclusion came from visual evidence or operator confirmation.

This is a task-contract milestone, not a durable proof of external effects. A screenshot cannot independently prove every send, upload, or save. Future typed integrations should provide receipts such as saved file hashes, sent-item IDs, or transaction references and attach them to the same contract.

The focused tests cover planner parsing, persistence into the execution policy, and rejection when one criterion fails. The Electron fixture additionally renders the review card with criteria and supplied personal context.
