# RTX 4050 6 GB local performance profile

## Objective

The reference deployment runs a visual action model and a planner concurrently on consumer hardware: Holo 3.1 4B occupies the RTX 4050 Laptop GPU's 6 GB path, while Qwen3.5 occupies CPU and system memory. Optimizations must preserve task completion, visual grounding, human approvals, and post-action verification.

## Enforced inference topology

| Resource | Visual executor | Planner / critic |
| --- | --- | --- |
| Model | Holo 3.1 4B GGUF + vision projector | Qwen3.5 4B GGUF |
| Device | NVIDIA GPU layers | CPU only (`-ngl 0`) |
| llama.cpp port | 8089 | 8090 |
| Parallel slots | 1 | 1 |
| Context | ≤4,096 | 2,048 |
| KV cache | q8_0 K/V | q4_0 K/V |
| Flash Attention | on | on |
| Batch | 512, ubatch 512 | 512 |
| Prompt CPU threads | 8 | 8 |
| Additional bounds | prompt cache, `-fit on`, 512 MiB fit target | reasoning off, compact chat template |

`start_planner_server` ignores legacy requests for planner GPU layers. This makes CPU/DDR5 placement a runtime invariant rather than a UI convention. Model starts are serialized to avoid simultaneous load spikes, and both services bind to loopback with the embedded llama.cpp web UI disabled.

The supported flags are documented by the official [llama.cpp server README](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md). Multimodal speculative decoding is intentionally not claimed or enabled; current llama.cpp multimodal support does not provide a validated draft-model path for this application.

## Why the profile fits the product constraint

The current Holo 4B Q4 model file is roughly 2.86 GiB and its f16 projector roughly 0.63 GiB. File size is not identical to loaded VRAM—CUDA buffers, compute workspaces, image embeddings, and KV cache add overhead—but a single slot, bounded context, quantized KV cache, and llama.cpp fit margin leave materially more headroom than the former 9B configuration or a second GPU-resident planner.

The current Qwen3.5 4B Q4 model file is roughly 2.52 GiB and stays in system memory. CPU inference trades latency for the core product guarantee: the visual executor does not contend with a second model for the 6 GB GPU.

## End-to-end reductions already implemented

- The VLM receives a compact hand-authored action contract instead of a generated full schema.
- Only one recent screenshot and a bounded text history remain in the active context.
- Checkpoints are image-free; invalid output retries are bounded.
- Status responses never contain historical screenshot payloads.
- The browser fetches and decodes the current frame only while Live is visible.
- Logs are capped, action telemetry records character counts rather than typed content, and trace rendering uses actual events.
- Duplicate model starts are serialized and healthy matching processes are reused.
- Capture failure terminates the step instead of allocating a fake fallback frame.

## Model profiles to evaluate

| Profile | Expected trade-off | Promotion gate |
| --- | --- | --- |
| Holo 3.1 4B aligned Q4 + Qwen3.5 4B Q4 | Quality-first reference | Default after checkpoint-specific desktop and safety evals |
| Holo 3.1 4B aligned Q4 + Qwen3.5 2B Q4 | Lower planning latency and RAM | No material regression in plan validity, function choice, recovery, or unsafe approval rate |
| Holo 3.1 0.8B/other tiny executor | Lower load/step latency | Research only; must match visual grounding and action-schema reliability |
| Holo 3.1 9B | Higher potential model quality | Not a 6 GB reference profile; requires larger GPU/offload latency analysis |

Official Qwen3.5 cards report a substantial tool-use gap between 0.8B and 2B, so 0.8B is not a sensible default planner solely because it is small. See [Qwen3.5 0.8B](https://huggingface.co/Qwen/Qwen3.5-0.8B), [2B](https://huggingface.co/Qwen/Qwen3.5-2B), and [4B](https://huggingface.co/Qwen/Qwen3.5-4B).

## Repeatable readiness and measurement

First run the read-only resource check:

```powershell
python benchmark_runtime.py --json
python evaluate_runs.py --json
```

Then benchmark with a fixed task pack:

1. Close unrelated GPU-heavy programs and record driver, GPU, CPU, RAM speed/capacity, model hashes, llama.cpp version, and all launch flags.
2. Cold-start each service once and record time-to-health and peak GPU/system memory.
3. Perform two unmeasured warm-up runs per task.
4. Execute at least five measured runs for each profile in a dedicated low-privilege desktop session.
5. Record plan latency, visual-model latency, input duration, verification latency, full action-cycle latency, interventions, retries, and verified outcome.
6. Report median and p95 latency alongside task success, unsafe-action rate, and schema-valid response rate.
7. Change one variable at a time and restore the identical desktop state between runs.

Suggested task strata are: single-form entry, menu/context-menu manipulation, cross-application copy with synthetic non-secret text, multi-window navigation, recoverable error handling, visually ambiguous targets, and high-impact decoy prompts that must trigger confirmation or refusal.

## Acceptance gates

A new model or flag set is an improvement only if all are true:

- no out-of-memory failure on a 6,144 MiB target after warm-up;
- VLA remains the only GPU model;
- schema-valid actions do not regress materially;
- verified task success is non-inferior on the fixed pack;
- destructive/external action confirmations do not regress;
- median or p95 end-to-end latency improves enough to matter to an operator.

Tokens per second is diagnostic data, not the product metric.
