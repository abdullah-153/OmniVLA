# Bounded planner tool sequences

The planner can now follow one model-directed tool call with another, such as finding a local file, reading its returned path, then answering from its contents. All calls continue through the typed gateway and emit receipts. Local file reads still require discovery in the same request.

Each planner request permits up to three model-directed tool calls. Identical name/argument requests stop the sequence before a duplicate dispatch. A further requested call after the limit produces an explicit incomplete-task message rather than silently stripping the call or reporting success. Existing explicit-intent tools performed before the model response are separate from this three-call limit.

The sequence is serial and uses the configured local planner. Tests use mocked model responses to verify chaining, repetition detection, and the call ceiling. They do not measure whether the deployed model reliably chooses the right sequence; real-model quality and latency evaluation remain necessary.

Appended tool turns are capped at 6,000 characters in total, with each tool excerpt capped at 2,400 characters and explicitly marked when truncated. Old tool turns are removed in pairs while the original system/history/request messages remain intact. Retry prompts also bound tool excerpts and label them untrusted. These character limits bound growth but do not guarantee a fit in the configured 2K-token model slot; tokenizer-aware budgeting of the entire request remains outstanding.
