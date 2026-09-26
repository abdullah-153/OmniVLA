# Memory corrections and freshness

The personal context store is used to select task-relevant preferences, facts, linked entities, and past workflows for planning. A user can now forget an individual sourced record from **Settings → Personal learning → Memory sources**. Forgetting a record also removes the preference, project-scoped preference, or fact that it supplies, so it cannot continue to influence a later plan. Linked entities and relations retain their existing individual Forget controls.

Successful workflows are retrieval hints, not instructions. They are supplied to the planner only for 90 days after the successful task. Older workflows are pruned when a new successful workflow is learned. Explicit user preferences and facts have no automatic expiry; the user can correct or forget them individually.

This does not establish that an old external account, document, or screen state still exists. The planner must ground each new task in current observations and obtain required review before execution. The memory source UI shows provenance for corrections, but that provenance is a past user statement or setting, not a fresh verification of an external effect.
