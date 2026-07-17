# Local Performance Profile

## Objective

OmniVLA is designed to remain responsive on a laptop-class NVIDIA GPU with 6 GB of VRAM while retaining a local vision-language executor and a separate critic. The target is lower end-to-end latency per meaningful action, not simply faster model decoding at the cost of weaker safety checks.

## Implemented profile

| Area | Setting | Why it matters |
| --- | --- | --- |
| GPU ownership | Holo VLA uses GPU layers; planner/critic uses CPU (`-ngl 0`) | Prevents two models from competing for the same small VRAM pool. |
| Server concurrency | One llama.cpp slot per server (`-np 1`) | Prevents parallel requests from multiplying KV-cache pressure. |
| VLA context | Capped at 4,096 tokens | Keeps memory and prefill latency bounded for a local visual executor. |
| Critic context | 2,048 tokens | A critic decision is short; a full VLA context is unnecessary. |
| KV cache | q8_0 for VLA, q4_0 for critic | Trades a small amount of cache precision for substantially lower memory pressure. |
| Prefill | Flash Attention, prompt caching, batch size 512, 8 CPU prompt threads | Cuts repeat prompt work and improves prompt ingestion on common consumer CPUs. |
| Agent context | Compact JSON action contract, ten-message rolling window, image-free checkpoints | Eliminates avoidable prompt tokens and avoids repeatedly retaining large JPEG payloads. |
| Telemetry | Phase and timing callbacks | Makes real model, action, verification, and total-cycle time observable in the UI. |

The tuning uses supported llama.cpp server flags, including server-slot control and prompt caching. See the official [llama.cpp server documentation](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md) and [CLI documentation](https://github.com/ggml-org/llama.cpp/blob/master/tools/cli/README.md).

## Safety and fidelity boundaries

The profile does not add a second visual-change detector or run a duplicated perception pipeline. OmniVLA retains its existing verifier, critic, allowed-input routing, and human confirmation flows. It instead removes redundant prompt/schema/image handling that added latency without contributing new evidence.

The execution budget is still configurable. It is intentionally not presented as a fake completion percentage: the web command center and desktop overlay report the number of actions actually recorded, the current phase, and the latest measured timing. A budget stop remains a protective boundary, not proof that a task is complete.

## Repeatable measurement procedure

1. Launch the app normally with `python run_agent_gui.py`; do not run other GPU-heavy programs.
2. Wait for the VLA and CPU critic to report ready, then run the same low-risk task twice as warm-up. Do not include those two runs in the comparison.
3. Run the task three more times and record the UI's **Last cycle** time along with model, action, and verification phases.
4. Change one setting at a time only if needed. On a 6 GB GPU, keep parallel slots at one and VLA context at or below 4,096.
5. Report median cycle time and task success rate together. A faster setting that lowers verified completion is not an improvement.

## Expected effect

The former 40–50 second step time can have several causes: GPU contention from a critic, excessive prompt prefill, image-heavy checkpoint copies, cold model startup, or slow desktop actions. This profile directly removes the first three and exposes the last two in the timing breakdown. Actual latency remains hardware-, model-, task-, and warm-up-dependent, so the product records it rather than claiming a fixed speed-up.
