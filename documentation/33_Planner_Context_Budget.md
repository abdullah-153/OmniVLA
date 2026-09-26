# Measured planner context budget

The text planner's context remains 2,048 tokens. Before initial chat planning,
tool-response synthesis, and its concise retry, the app renders the current
server chat template and tokenizes it. The budget reserves the requested output
allowance plus 64 tokens for delimiters/template differences.

When needed, fitting removes older conversation/tool turns and complete optional
memory/recall blocks, then shortens designated evidence excerpts with an explicit
truncation marker. Core system instructions and the full current request remain.
The previous silent 1,600-character cutoff of the current request is removed.
If required content still cannot fit, the app asks for a smaller request instead
of silently dropping its tail. If token counting is unavailable, planning fails
explicitly rather than sending an unmeasured request.

The implementation uses llama.cpp's documented
[/apply-template and /tokenize endpoints](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md#post-apply-template-apply-chat-template-to-a-conversation).
It counts model special tokens and uses the same server as inference. These checks
cover the text chat-planner path; separate vision and memory-extraction calls are
outside this milestone. Truncation can remove relevant evidence, so partial
answers must remain qualified. A measured fit does not establish answer quality.

Unit tests cover Unicode evidence, preserved request tails and grounding rules,
tool evidence, server-template use, and failure without a tokenizer. Existing
offline planner tests inject a fake token counter alongside mocked inference;
they do not demonstrate real tokenizer behavior. Run the opt-in live check with
`python evaluate_context_budget.py --output scratch/context-budget.json` to verify
real token counts and inference on oversized synthetic evidence.

## Validation on the configured local model

The full regression suite passed: **319 tests**. On Spark-X2.5-4B Q4_K_M, the
oversized synthetic prompt counted 26,080 tokens before fitting and 1,699 after
fitting. Inference independently reported 1,699 prompt tokens. With 256 tokens
reserved for output and the 64-token margin, it remained inside the 2,048-token
slot. The request was preserved, the evidence excerpt was marked as truncated in
the prompt, and the answer correctly reported the supplied status. Raw results
are in `33_Planner_Context_Result.json`. This is one functional case, not a
tokenizer conformance test across all models/templates.

All three existing live project-memory cases also passed with budgeting enabled
(`33_Project_Memory_Budget_Result.json`). The general discovery case exercised
the bounded query fallback from `Atlas status` to `status`, then read the correct
file as confirmed by its digest. These runs shared CPU resources with regression
tests; their timing is not a controlled performance comparison.
