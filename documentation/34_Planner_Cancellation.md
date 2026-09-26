# Planner cancellation

The chat composer now offers **Stop planning** while a planner request is active.
The control calls the authenticated Stop endpoint. Planning transitions through
stopping until the worker returns; the composer cannot submit overlapping work.

A shared cancellation event is reset only when a new planner/recovery request
owns the planner lock. Checks run before startup and tool dispatch, after model
responses, after recording tool receipts, and before publishing a final answer.
Cancelled model extraction cannot apply its returned memory updates. A late
answer cannot replace the stopped chat or create a reviewed plan. Receipts for
tools that completed before cancellation are retained with the stopped message.

Cancellation is cooperative. It does not terminate a model HTTP request or an
already-running tool, undo a notification, or erase context learned earlier in
the request. The UI waits for the in-flight operation to return or time out before
the planner lock is released. No subsequent tool or synthesis request is started
after cancellation is observed.

Regression tests cover cancellation during a model reply that tries to send a
notification, cancellation after a completed search, and suppression of a late
answer at the persistence boundary. The hidden Electron smoke harness exercises
the visible button against a delayed fixture planner and confirms the stopped
message. Existing desktop approval and overlay checks also pass, with no renderer
console errors. The desktop control was inspected in a captured screenshot.
The fixture does not use real model inference or external effects.

Validation: the full suite passed 322 tests. A subsequent refinement classifies
an in-flight error arriving after Stop as cancellation; all 66 focused safety and
planner-sequence tests passed after that change. The fixture server was shut down
after the Electron checks.
