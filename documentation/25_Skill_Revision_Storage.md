# Skill revision storage

`SkillRegistry.save_skill` retains the previous source before replacing a skill. Snapshots live in the skill's `.history` directory, named by SHA-256 digest and original Markdown or JSON format. History directories are excluded from skill discovery, so old procedures cannot become additional executable skills.

`list_revisions(name)` exposes the retained revisions. `restore_revision(name, digest)` checks the snapshot digest, parses it, and saves it as the current skill while retaining the version it replaces. Damaged snapshots fail without changing the active skill.

This is a registry API foundation. A console history view and evaluation results per revision remain to be implemented. Snapshots are local recovery copies, not tamper-proof audit records, and currently have no automatic retention limit.
