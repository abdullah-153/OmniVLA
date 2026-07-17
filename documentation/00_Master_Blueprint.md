# OmniVLA: Master Project Blueprint
## A Zero-Telemetry, Memory-Augmented GUI Agent for 6GB Edge Devices

---

## Executive Summary

OmniVLA is a **local-first, privacy-preserving GUI automation agent** designed to operate complex desktop applications, websites, and workflows entirely on consumer-grade hardware (RTX 4050, 6GB VRAM). Unlike cloud-based solutions or massive VLM deployments, OmniVLA achieves reliable GUI automation through a **Decoupled Cognitive Pipeline** — separating perception, reasoning, and execution into specialized modules that individually stay within the capability ceiling of small local models.

### The Central Thesis

> **Reliable GUI automation on 6GB VRAM is achievable — not by building a single all-knowing model, but by designing an architecture where each component operates within its competence boundary.**

---

## Why Existing Approaches Fail (Root Cause Analysis)

Before presenting the solution, we must precisely diagnose *why* common approaches fail with small (3-4B parameter) local models. This analysis informed every architectural decision in OmniVLA.

### 1. Set-of-Mark (SOM) Failures

| Problem | Root Cause | Impact |
|---------|-----------|--------|
| Model can't point to correct label | SOM markers are visual overlays — the model must correlate a tiny numbered marker with a specific UI element. 3-4B VLMs lack the spatial reasoning precision for this. | ~40% click accuracy on complex UIs |
| Non-obvious elements get no marker | SOM relies on heuristic detection (usually YOLO/contour-based). Custom controls, canvas elements, and non-standard widgets are missed entirely. | Agent is blind to 30-50% of interactive elements |
| Cognitive overload | A screen with 50+ SOM markers creates an overwhelming visual grid. Small models can't discriminate among dozens of numbered bubbles. | Hallucination rate increases with element density |

**Verdict**: SOM reduces the agent to a "dumb number-picker" — it removes semantic understanding and replaces it with spatial guessing.

### 2. UI Tree / Accessibility Tree Failures

| Problem | Root Cause | Impact |
|---------|-----------|--------|
| Elements hidden layers deep | UI trees are hierarchical. The button you want might be `Window > Frame > Panel > TabControl > TabItem > ScrollViewer > StackPanel > Button`. | Context explosion: 200+ tokens just to describe one button's path |
| Tree passing makes inference slow | A full UI tree for a complex app like Excel can have 500-2000 nodes. Even compressed, this exceeds the effective context window of a 4B model. | Inference time: 3-8 seconds per step |
| Tree is often incomplete | Electron apps, custom-rendered UIs, web canvases, and game engines have opaque accessibility trees. | Agent fails silently on modern apps |
| LLM can't navigate tree structure | Small models struggle with deeply nested JSON/XML structures. They lose track of parent-child relationships beyond 3-4 levels. | Hallucinated element references |

**Verdict**: Passing raw trees makes the LLM process *structure* instead of *semantics*. It's the wrong abstraction level for a small model.

### 3. Grid / Sub-Grid Failures

| Problem | Root Cause | Impact |
|---------|-----------|--------|
| Model can't point to correct grid cell | Grid division is arbitrary — it has no relationship to UI element boundaries. The model must map semantic intent to geometric coordinates. | ~35% correct grid selection |
| Sub-grid hallucination | After selecting a coarse grid, the model must select a sub-grid within it. This compounds the error: even 70% accuracy at each level yields only 49% end-to-end. | Cascading error multiplication |
| Elements split across grids | UI elements rarely align with grid boundaries. A button might span two cells, or a dropdown might cross four cells. | Ambiguous targeting |
| No semantic grounding | Like SOM, grids treat UI as geometry, not semantics. The model becomes a coordinate guesser, not an intelligent agent. | Cannot handle context-dependent actions |

**Verdict**: Grid approaches compound errors at each refinement level and ignore semantic meaning entirely.

### 4. The Common Root Cause

All three approaches share a **single fundamental flaw**:

> **They force the LLM to do everything in one forward pass** — perceive the screen, understand the UI semantics, plan the action, and precisely locate the target element — all simultaneously.

A 3-4B model simply does not have the capacity for this multi-faceted reasoning in a single inference step. The solution is **decomposition**: break the problem into stages where each stage is within the model's competence.

---

## The Solution: Decoupled Cognitive Pipeline

OmniVLA replaces the monolithic "see-and-click" paradigm with a **five-stage pipeline** where each stage has a narrow, well-defined responsibility:

```
┌──────────────────────────────────────────────────────────────────────┐
│                    USER TASK (Natural Language)                       │
│                "Rename the Budget sheet in Excel to Q4 2026"         │
└──────────────────┬───────────────────────────────────────────────────┘
                   │
                   ▼
┌──────────────────────────────────────────────────────────────────────┐
│  STAGE 1: TASK DECOMPOSER (LLM — Text Only)                         │
│  Breaks high-level goal into atomic sub-goals                        │
│  Output: ["Right-click Budget tab", "Click Rename", "Type Q4 2026"] │
└──────────────────┬───────────────────────────────────────────────────┘
                   │ For each sub-goal:
                   ▼
┌──────────────────────────────────────────────────────────────────────┐
│  STAGE 2: SEMANTIC PERCEPTION ENGINE (No LLM — APIs + CV)           │
│  Extracts compressed UI state: elements, labels, types, positions    │
│  Sources: UIA APIs → OCR fallback → YOLO fallback                   │
│  Output: ~150-200 token JSON semantic state                         │
└──────────────────┬───────────────────────────────────────────────────┘
                   │
                   ▼
┌──────────────────────────────────────────────────────────────────────┐
│  STAGE 3: ACTION REASONER (LLM — Text Only, Constrained)            │
│  Maps semantic state + sub-goal → single atomic action               │
│  Uses GBNF grammar: can ONLY output valid actions                    │
│  Output: click(element_id) | type("text") | key(shortcut)           │
└──────────────────┬───────────────────────────────────────────────────┘
                   │
                   ▼
┌──────────────────────────────────────────────────────────────────────┐
│  STAGE 4: ACTION EXECUTION LAYER (No LLM — Deterministic)           │
│  Converts semantic action → system input                             │
│  Fallback chain: Keyboard shortcut → UIA Invoke → PyAutoGUI click   │
└──────────────────┬───────────────────────────────────────────────────┘
                   │
                   ▼
┌──────────────────────────────────────────────────────────────────────┐
│  STAGE 5: VERIFICATION & MEMORY (No LLM — Heuristic + DB)           │
│  Verifies action effect via screen diff + semantic re-parse          │
│  Stores successful trajectories in ChromaDB for future retrieval     │
└──────────────────────────────────────────────────────────────────────┘
```

### Why This Architecture Works

| Design Principle | Implementation | Benefit |
|-----------------|---------------|---------|
| **Separation of Concerns** | Each stage has ONE job | No single module is overloaded |
| **LLM sees text, not pixels** | Perception converts visuals → text | ~200 token context instead of 1000+ visual tokens |
| **Constrained Output** | GBNF grammar restricts LLM output space | Structurally impossible to hallucinate malformed actions |
| **API-First Perception** | UIA/Win32 APIs extract elements directly | Zero LLM cost for perception on native apps |
| **Deterministic Execution** | Actions are executed programmatically | No coordinate guessing |
| **Memory-Augmented Learning** | ChromaDB stores successful trajectories | Agent improves with usage |

---

## Document Suite Overview

This documentation suite is organized into **8 comprehensive guides**, each covering a major subsystem or concern:

| # | Document | Purpose | Key Topics |
|---|----------|---------|------------|
| 01 | [System Architecture](./01_System_Architecture_Deep_Dive.md) | Overall system design and data flow | Pipeline architecture, VRAM budgeting, module interfaces |
| 02 | [Perception Engine](./02_Perception_Engine.md) | How the agent "sees" the screen | UIA-first strategy, OCR/YOLO fallback, semantic compression |
| 03 | [Task Decomposition](./03_Task_Decomposition.md) | Breaking complex tasks into steps | Hierarchical planning, app-aware decomposition, error recovery |
| 04 | [Action Reasoning](./04_Action_Reasoning.md) | How the LLM decides what to do | Constrained decoding, GBNF grammars, prompt engineering |
| 05 | [Execution Layer](./05_Execution_Layer.md) | How actions become system inputs | Shortcut routing, UIA invocation, coordinate fallback |
| 06 | [Memory & Verification](./06_Memory_And_Verification.md) | Learning from experience | Episodic memory, trajectory storage, screen diffing |
| 07 | [Model Selection & Optimization](./07_Model_Selection_And_Optimization.md) | Choosing and deploying the LLM | Gemma 4 vs Qwen 3.5, quantization, VRAM optimization |
| 08 | [Advanced Strategies & Research](./08_Advanced_Strategies_Research.md) | SOTA techniques and future directions | GOLD, RegionFocus, SE-GUI, GUI-Actor, ShowUI integration |

---

## Hardware Constraints & VRAM Budget

The entire system is designed for a strict 6GB VRAM envelope:

```
┌─────────────────────────────────────────────────────────────────┐
│                    RTX 4050 — 6144 MB VRAM                       │
├──────────────────────────────┬──────────────────────────────────┤
│  LLM (Q4_K_M quantized)     │  ~4200-4600 MB                  │
│  KV Cache (2048 ctx)         │  ~600-800 MB                    │
│  CUDA Overhead               │  ~200-300 MB                    │
├──────────────────────────────┼──────────────────────────────────┤
│  TOTAL GPU                   │  ~5200-5700 MB                  │
│  HEADROOM                    │  ~400-900 MB                    │
├──────────────────────────────┴──────────────────────────────────┤
│  CPU RAM Budget                                                  │
│  OCR Engine (EasyOCR/PaddleOCR)  │  ~400 MB                   │
│  ChromaDB + Embeddings           │  ~300 MB                   │
│  Screen Capture (mss + PIL)      │  ~100 MB                   │
│  Python Runtime + Libraries      │  ~400 MB                   │
│  TOTAL CPU                       │  ~1200 MB                  │
└──────────────────────────────────────────────────────────────────┘
```

### Critical Constraint: One Model at a Time

With 6GB VRAM, we **cannot** run a VLM (vision-language model) alongside a text LLM. This eliminates architectures like OmniParser (which requires a separate YOLO + Florence-2 on GPU) running concurrently with the reasoning LLM.

**Solution**: The perception pipeline runs entirely on CPU (UIA APIs + CPU-based OCR). Only the reasoning LLM occupies the GPU.

---

## Technology Stack

| Component | Technology | Runs On | Rationale |
|-----------|-----------|---------|-----------|
| **LLM Inference** | llama.cpp / Ollama | GPU (CUDA) | Fastest local inference, GGUF support, GBNF grammars |
| **LLM Model** | Gemma 4 E4B (Q4_K_M) or Qwen 3.5 | GPU | Native function calling, vision-capable, edge-optimized |
| **Screen Capture** | mss | CPU | <5ms capture, zero GPU allocation |
| **OCR** | EasyOCR / PaddleOCR | CPU | Accurate, CPU-friendly, multilingual |
| **UI Automation** | pywinauto (UIA backend) | CPU | Direct Win32/UIA API access, zero inference cost |
| **Element Detection** | Custom heuristics + UIA | CPU | Deterministic, no model needed |
| **Memory DB** | ChromaDB (persistent) | CPU | Local vector DB, no cloud dependency |
| **Embeddings** | all-MiniLM-L6-v2 | CPU | 22MB model, negligible overhead |
| **Execution** | pyautogui + pywinauto | CPU | System input simulation, UIA control invocation |
| **Orchestration** | Python asyncio | CPU | Lightweight, no framework overhead |

---

## Project Roadmap

### Phase 1: Foundation (Weeks 1-2)
- [ ] Implement robust UIA-first perception engine
- [ ] Build semantic state compression to <200 tokens
- [ ] Set up llama.cpp server with Gemma 4 E4B
- [ ] Implement GBNF grammar-constrained action reasoning
- [ ] Basic action execution via pyautogui

### Phase 2: Intelligence (Weeks 3-4)
- [ ] Implement task decomposer with hierarchical planning
- [ ] Build shortcut knowledge base for common apps
- [ ] Implement UIA-based direct element invocation
- [ ] Screen diffing and semantic verification
- [ ] ChromaDB episodic memory system

### Phase 3: Robustness (Weeks 5-6)
- [ ] Hybrid UIA + OCR fallback pipeline
- [ ] Error recovery and re-planning logic
- [ ] Complex app support (Excel, browsers, IDEs)
- [ ] Multi-step workflow execution
- [ ] Performance optimization and latency reduction

### Phase 4: Advanced (Weeks 7-8)
- [ ] GOLD-style global-to-local visual refinement
- [ ] RegionFocus-inspired test-time scaling
- [ ] QLoRA fine-tuning on GUI grounding datasets
- [ ] Comprehensive evaluation on real-world tasks
- [ ] Documentation and deployment packaging

---

## Success Metrics

| Metric | Target | Current Baseline |
|--------|--------|-----------------|
| **Click Accuracy** (native apps) | >90% | ~40% (SOM-based) |
| **Click Accuracy** (web apps) | >80% | ~35% (SOM-based) |
| **Task Completion Rate** (simple) | >85% | Not tested |
| **Task Completion Rate** (complex) | >60% | Not tested |
| **Per-Step Latency** | <2 seconds | ~4-8 seconds |
| **VRAM Usage** | <5.5 GB | ~4.6 GB (model only) |
| **Privacy** | 100% local | 100% local ✓ |

---

## How to Read This Documentation

1. **Start here** (00_Master_Blueprint) for the big picture
2. Read **01_System_Architecture_Deep_Dive** for detailed data flow
3. Read module-specific documents (02-06) for implementation details
4. Read **07_Model_Selection** for LLM deployment decisions
5. Read **08_Advanced_Strategies** for SOTA research integration

Each document is self-contained but cross-references related documents. All documents are written to be printable as standalone PDF guides.

---

*Document Version: 1.0 | Last Updated: April 27, 2026*
*Project: OmniVLA — Final Year Project*
