# Repeatable skill routing evaluation

Run `python evaluate_skill_routing.py cases.json --skills-dir skills --output report.json` to evaluate a labeled JSON array against a skill library. Each case has `id`, `prompt`, `expected_skill` (name or null), and optional `expected_parameters`. A nonzero exit status indicates a regression or invalid input. Reports include skill content fingerprints, selected versus expected names, pass counts, false selections for abstention cases, and routing latency. Prompts and extracted parameter values are omitted from the output report.

Example cases:

```json
[
  {"id": "explicit", "prompt": "Use @browser_search", "expected_skill": "browser_search"},
  {"id": "unrelated", "prompt": "Play music", "expected_skill": null}
]
```

The library must contain every non-null expected skill. Keep cases outside the skill discovery directory. Equal strongest automatic matches now abstain rather than choosing alphabetically; an explicit skill mention still selects that skill.

This evaluates deterministic routing and parameter capture only. It launches no model, performs no desktop actions, and cannot establish end-to-end task success. Real-model task evaluation remains necessary before claiming quality improvements.
