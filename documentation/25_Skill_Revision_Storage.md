# Skill revision storage

`SkillRegistry.save_skill` retains the previous source before replacing a skill. Snapshots live in the skill's `.history` directory, named by SHA-256 digest and original Markdown or JSON format. History directories are excluded from skill discovery, so old procedures cannot become additional executable skills.

`list_revisions(name)` exposes the retained revisions. `current_revision(name)` hashes the exact saved source bytes. `restore_revision(name, digest)` checks the snapshot digest, parses it, restores those exact bytes, and retains the version it replaces. Damaged snapshots fail without changing the active skill.

Imported JSON and Markdown skills are updated at their existing source path and retain their format. This avoids duplicate definitions that can resurrect the old procedure after restart. Identical saves do not create extra revisions; source writes use consistent UTF-8 bytes across platforms.

The authenticated skill detail endpoint includes revision metadata. Local authenticated clients can preview a snapshot with `POST /api/skills/revision` or restore it with `POST /api/skills/restore`, passing `name` and `revision`. Restore is rejected while a desktop task is running. Preview does not change the active source.

The Markdown editor includes version results and history with a read-only preview and explicit restore action beside the version selector. Restoring warns that unsaved editor changes will be replaced. Stale preview responses are ignored when selecting another revision or skill. The Electron fixture exercises preview and restore. Offscreen rendering is enabled for the hidden test window so screenshots reflect the current editor; the desktop preview and restore layout has been inspected.

Observed run totals and verification-source counts appear beside current and selected versions; they are not controlled evaluations. Snapshots are local recovery copies, not tamper-proof audit records, and currently have no automatic retention limit.
