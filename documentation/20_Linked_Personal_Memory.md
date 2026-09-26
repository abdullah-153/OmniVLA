# Linked personal memory

The personal profile now stores bounded, typed entities (`project`, `person`, `document`, `folder`) and links between them. An explicit statement such as “Project Atlas contact is Sarah Khan” or “Project Atlas uses document roadmap.pdf” creates a sourced relationship. Direct model-extracted relationships are accepted only when the user's quoted evidence contains both exact names and wording consistent with the relation.

When a task mentions a linked entity, context assembly retrieves its nearby links. Asking about Sarah can therefore surface Project Atlas, and asking about Atlas can surface its contact, document, and folder. Link direction is retained so the planner can distinguish “Atlas has contact Sarah” from the inverse. The plan review lists the personal records supplied to the planner.

Settings displays the entities and links with their sources and individual **Forget** controls. Removing an entity removes its attached links. The `/api/profile` endpoint supports explicit creation and deletion. Clearing learned context removes conversation-learned graph records; relationships explicitly saved in Settings survive it.

Version 2 profiles are backed up and migrated to version 3 without dropping existing facts or preferences. Limits are 100 entities and 200 links. This graph is still based on explicit statements; it does not infer ownership or permission from a filename, webpage, or address. The next step is to add confidence, expiry, and richer correction handling, then measure whether linked retrieval improves real tasks.
