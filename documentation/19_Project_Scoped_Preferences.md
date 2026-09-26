# Project-scoped personal preferences

The personal profile can now store a preference for a named project without overwriting the user's global setting. For example, “For Project Atlas, use Gmail for email” applies Gmail to Atlas email work while other email tasks retain the global provider. Corrections replace the scoped value. Clearing learned context removes conversation-learned scopes while retaining preferences set explicitly in Settings.

Deterministic extraction handles the direct “For Project …, use … for email/browser” wording. Model-assisted extraction also accepts an explicit project scope, but it must appear in the user's own quoted evidence. If the model labels an explicit project statement as global, the project is applied as its scope instead.

Task context names active scopes, and the plan review shows the scoped value among context supplied to the planner. This remains a narrow first step toward a richer project/person/document model. It does not infer project relationships from arbitrary files or conversations, and it does not grant permission to use a connected account.

If one request names multiple projects with incompatible values for the same preference, the context pack omits that preference and identifies the conflict for clarification.
