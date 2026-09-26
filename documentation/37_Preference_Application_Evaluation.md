# Preference application: live failures and fixes

Run `python evaluate_personal_preferences.py --output scratch/preference-results.json`.
The default response allowance is 640 tokens, matching the desktop planner cap.
The runner uses isolated synthetic preferences, disables learning and external
tools, and checks that stored memory remains unchanged. It covers global default,
matching project, unrelated project, explicit current-request override, and
conflicting project defaults. Lexical scoring remains limited and requires manual
answer review; it is not a general semantic evaluator.

## Failures observed

The initial run used a 320-token allowance. The model correctly answered the three
default-selection cases, but chose saved Gmail despite an explicit instruction
to use Outlook for this message. It also suggested both services for a single
joint update instead of asking which one to use. The initial lexical conflict
check falsely accepted that response because it mentioned both names and ended
with an unrelated question. The raw initial result is retained; manual review
establishes that this case failed. Scoring now requires a service-choice question
and rejects the observed “both services” workaround.

Removing the conflicting saved defaults alone still failed: the model attempted
a web lookup for the requested service. That intermediate result is also retained.

## Runtime changes

Recognized explicit one-off email/browser instructions now suppress conflicting
saved defaults from the current context. A separately labeled `task_overrides`
field supplies the current choice. Neither operation modifies stored memory.
Detection is deliberately bounded to clear phrases such as “For this message,
use Outlook for email” or “Use Outlook instead”; quoted examples are excluded.
Unrelated preference categories remain available. Arbitrary language and all
possible preference categories are not covered by this recognizer.

For unresolved application choices across projects, the runtime asks the user to
choose rather than asking the model to reconcile incompatible defaults. Explicit
comparison/list questions still go to the planner. The clarification is generated
from stored facts and does not execute a tool or produce a desktop plan. This is
a runtime clarification, not evidence that the model learned conflict handling.

## Final validation

At the 640-token allowance, all five cases passed. Four were model answers; the
conflict case was a deterministic clarification. The explicit override returned
Outlook in 8.2 seconds, with no tool calls and unchanged memory. The other defaults
remained correctly scoped. Results are in `37_Personal_Preferences_Result.json`.
The regression set covers quoted instructions, preserved unrelated defaults,
unchanged storage, explicit conflict resolution, and bypassing inference for
unresolved choices. These small examples do not establish general task success or
correct execution in real email applications.

The full regression suite passed 344 tests. Afterward, a final formatting guard
was added to prevent stored preference labels from introducing desktop-plan
fences or new steps into clarification text; all six focused preference tests
passed with that guard. Stored values themselves are not modified.
