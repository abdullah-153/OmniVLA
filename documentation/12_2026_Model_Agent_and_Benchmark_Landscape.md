# 2026 model, agent, and benchmark landscape

Research date: 20 August 2026. Sources are official model cards, vendor documentation, research project repositories, and benchmark repositories.

## Executive decision

Keep OmniVLA's reference architecture: a compact, specialized visual executor on the 6 GB GPU and a compact planner/critic on CPU/DDR5. The closest current research precedent is Microsoft's MagenticLite split between a small orchestrator and specialized Fara executor. Large hosted generalists are valuable optional providers and evaluation references, but making them mandatory would erase OmniVLA's local consumer-hardware differentiation.

The practical near-term model change is not “use the newest large model.” It is:

1. replace the default abliterated Holo 3.1 4B quant with a compatible aligned 4B quant;
2. keep Qwen3.5 4B as the quality baseline;
3. A/B Qwen3.5 2B as a lower-latency CPU planner;
4. promote only on end-to-end success and safety, not model-card averages.

## Model landscape

| Model/family | Relevant capability | Deployment fit for OmniVLA | Decision |
| --- | --- | --- | --- |
| [Holo 3.1](https://hcompany.ai/holo3.1) / [Holo 3.1 4B card](https://huggingface.co/Hcompany/Holo-3.1-4B) | Native cross-environment computer use with compact sizes including 0.8B, 4B, 9B, and 35B | 4B is the strongest direct fit for a 6 GB visual executor | Keep 4B; prefer aligned weights; treat 0.8B as research and 9B+ as outside reference hardware |
| [Qwen3.5 4B](https://huggingface.co/Qwen/Qwen3.5-4B) | Compact general reasoning/tool use | Quality-first CPU/DDR5 planner | Keep as baseline |
| [Qwen3.5 2B](https://huggingface.co/Qwen/Qwen3.5-2B) | Smaller planner with materially stronger official tool-use results than 0.8B | Best candidate for lower CPU latency/RAM | Implemented configurable path; benchmark before promotion |
| [Qwen3.5 0.8B](https://huggingface.co/Qwen/Qwen3.5-0.8B) | Very small local model | Attractive memory use but official tool-use gap is large | Do not make default planner |
| [Fara 1.5](https://www.microsoft.com/en-us/research/articles/fara1-5-computer-use-agent/) | Compact computer-use executor optimized for browser interaction | Useful architectural reference; narrower than OmniVLA's cross-desktop goal | Evaluate only for browser-specialized profile |
| [GPT-5.6 models](https://developers.openai.com/api/docs/models) + [computer use](https://developers.openai.com/api/docs/guides/tools-computer-use) | Hosted frontier reasoning and computer-use tool through Responses | Strong optional cloud baseline; not local and changes privacy/cost | Offer as optional provider/eval comparator |
| [Gemini 3.6 Flash computer use](https://ai.google.dev/gemini-api/docs/computer-use) | Hosted computer use across browser/desktop/mobile surfaces | Strong latency-oriented cloud comparator | Optional future provider, not local default |
| [Claude Sonnet 4.6](https://www.anthropic.com/news/claude-sonnet-4-6) | Hosted computer-use and prompt-injection improvements | Strong optional cloud baseline | Keep provider abstraction compatible; do not claim local fit |

Official Qwen3.5 2B results illustrate why size selection needs task metrics: its published BFCL-V4 and TAU2 scores are substantially above the 0.8B card's results. Those aggregate benchmarks are evidence for testing 2B, not proof it will plan OmniVLA desktop tasks correctly.

## Open agent projects

| Project | Distinctive feature | Lesson for OmniVLA |
| --- | --- | --- |
| [UI-TARS Desktop](https://github.com/bytedance/UI-TARS-desktop) | Desktop product around vision-action models, local/remote models, and visible trajectories | Runtime selection and trajectory inspection must be product surfaces |
| [Magentic-UI](https://github.com/microsoft/magentic-ui) | Human-centered web-agent orchestration, plans, approvals, co-planning | Keep plan review and intervention separate from chat |
| [MagenticLite](https://www.microsoft.com/en-us/research/blog/magenticlite-magenticbrain-fara1-5-an-agentic-experience-optimized-for-small-models/) | Small planner plus specialized computer-use executor | Validates asymmetric local model roles |
| [UFO](https://github.com/microsoft/UFO) | Windows-focused multi-agent application automation | Useful reference for Windows task decomposition and application boundaries |
| [OpenCUA](https://github.com/xlang-ai/OpenCUA) | Open infrastructure for training and evaluating computer-use agents | Reproducible task/environment data matters as much as a model swap |
| [ShowUI-Aloha](https://github.com/showlab/ShowUI-Aloha) | Open GUI agent research and deployment components | Compare visual grounding and action representation, not just planner quality |
| [OpenAdapt Flow](https://github.com/OpenAdaptAI/openadapt-flow) | Visual workflow authoring and reusable automation flows | Teaching should yield inspectable, editable procedural knowledge |

## Feature comparison

| Capability | OmniVLA state | Market implication |
| --- | --- | --- |
| Consumer 6 GB local visual model | Implemented reference profile | Primary differentiator versus cloud-only agents |
| CPU/DDR5 concurrent planner | Enforced | Preserves GPU headroom and follows compact orchestrator research |
| Cross-desktop native input | Implemented on Windows | Broader than browser-only agents, with higher safety burden |
| Plan review and action approvals | Implemented | Expected baseline for supervised computer use |
| Live evidence timeline | Implemented | Makes local latency/failures inspectable |
| Demonstration-to-skill workflow | Implemented, editable | Differentiates from one-off prompt execution |
| Task/environment benchmark integration | Readiness and hermetic tests implemented; external environment pack remains | Highest-value next research investment |
| OS/session isolation | Not implemented | Required before consequential unattended deployment |
| Public multi-user governance | Not implemented | Outside local FYP scope |

## Benchmark landscape and evaluation strategy

- [OSWorld](https://github.com/xlang-ai/OSWorld) established real computer tasks across applications.
- [OSWorld-V2](https://github.com/xlang-ai/OSWorld-V2) expands the difficulty and realism of long-horizon dynamic desktop evaluation.
- [WindowsAgentArena](https://github.com/microsoft/WindowsAgentArena) is directly relevant to Windows application automation.

Leaderboard scores are not portable product guarantees. OmniVLA should use them as environment/task references while maintaining a small target-hardware pack that records:

- task completion and semantic verification;
- action-schema validity and grounding error;
- unsafe action / missed confirmation rate;
- recovery attempts and operator interventions;
- cold start, plan, VLA, verification, full-cycle median and p95 latency;
- peak VRAM and system RAM;
- checkpoint, quant, prompt, llama.cpp build, and hardware identity.

## Prioritized roadmap

### Implemented in this overhaul

- hard CPU-only planner placement and 6 GB llama.cpp bounds;
- configurable planner checkpoint for 4B/2B experiments;
- strict fail-closed action parsing and broader desktop gestures;
- just-in-time visible-target risk confirmation;
- native teaching capture with sensitive text parameterization;
- privacy opt-in/clear controls and screenshot-free status;
- activity-led responsive Command Center and model-topology UI;
- readiness reporting and expanded hermetic regression coverage.

### Next model/evaluation work

1. Acquire a compatible aligned Holo 3.1 4B Q4 checkpoint and record its hash/license.
2. Define 20–40 resettable Windows tasks across the strata in the performance profile.
3. Compare Qwen3.5 4B and 2B under identical Holo weights and prompts.
4. Add prompt-injection and misleading-screen adversarial cases.
5. Compare one hosted frontier computer-use provider as an upper-bound reference, with the same outcome rubric.
6. Promote no checkpoint until it passes safety, task-success, and 6 GB resource gates.

This sequence protects the selling point: a model upgrade is valuable only when the whole supervised local system becomes faster, safer, or more successful on the target machine.
