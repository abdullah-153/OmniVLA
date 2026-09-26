# Repeatable skill routing evaluation

Run `python evaluate_skill_routing.py cases.json --skills-dir skills --output report.json` to evaluate a labeled JSON array against a skill library. Each case has `id`, `prompt`, `expected_skill` (name or null), optional `expected_parameters`, and optional `context_pack` for preference-aware cases. A nonzero exit status indicates a regression or invalid input. Reports include exact saved skill source fingerprints, selected versus expected names, pass counts, false selections for abstention cases, and routing latency. Prompts, context packs, and extracted parameter values are omitted from the output report.

Example cases:

```json
[
  {"id": "explicit", "prompt": "Use @browser_search", "expected_skill": "browser_search"},
  {"id": "unrelated", "prompt": "Play music", "expected_skill": null}
]
```

The library must contain every non-null expected skill. Keep cases outside the skill discovery directory. Equal strongest automatic matches now abstain rather than choosing alphabetically; an explicit skill mention still selects that skill.

Automatic routing also abstains when the matching trigger is negated. A skill can declare `application` and `preference_path` in its Markdown frontmatter, such as `Gmail` and `email.service`. Such a skill routes only when that application is named positively in the request or is the effective saved preference in the task context. Explicit `@skill` selection still takes precedence. The built-in Gmail summary skill declares this binding so a generic email request cannot silently choose Gmail when the user prefers Outlook or has not chosen an email application.

This evaluates deterministic routing and parameter capture only. It launches no model, performs no desktop actions, and cannot establish end-to-end task success. Real-model task evaluation remains necessary before claiming quality improvements.
