# OmniVLA: Model Selection & Optimization
## Document 07 — LLM Deployment on 6GB VRAM

---

## 1. The Model Constraint

The RTX 4050 has **6144 MB** of VRAM. After CUDA overhead (~200-300MB), we have **~5800MB** for the model, KV cache, and any other GPU operations. This is our hard ceiling.

### What Must Fit in VRAM

```
Model weights (quantized):     ~4000-4600 MB
KV Cache (context window):    ~500-800 MB
CUDA runtime overhead:         ~200-300 MB
────────────────────────────────────────────
TOTAL:                         ~4700-5700 MB
AVAILABLE:                     6144 MB
HEADROOM:                      ~400-1400 MB
```

**Key insight**: We can afford ONE model at a time, quantized to Q4_K_M or Q4_K_S. We cannot run a separate vision encoder alongside it.

---

## 2. Model Candidates

### 2.1 Gemma 4 E4B (Google DeepMind)

| Property | Value |
|----------|-------|
| **Architecture** | Mixture of Experts (MoE), 4B active parameters |
| **Total Parameters** | ~12B (but only 4B active per token) |
| **Context Window** | 8K (native), can extend to 32K |
| **Vision** | ✓ Native multimodal (image input) |
| **Function Calling** | ✓ Native structured output |
| **Quantized Size (Q4_K_M)** | ~4.2-4.6 GB |
| **KV Cache (2K context)** | ~600 MB |
| **Total VRAM** | ~5.0-5.4 GB |
| **Release Date** | April 2026 |
| **GGUF Available** | ✓ via llama.cpp |
| **Ollama** | `ollama run gemma4:e4b` |

**Strengths**:
- MoE architecture = better reasoning per VRAM dollar
- Native function calling = reliable structured output
- Edge-optimized = specifically designed for laptops/mobile
- Strong instruction following at 4B active params

**Weaknesses**:
- MoE models can be slower (expert routing overhead)
- Relatively new — community tooling still maturing
- Vision encoder adds VRAM cost if used for screenshots

**Verdict for OmniVLA**: ✅ **Primary recommendation**. The MoE architecture gives better reasoning than a dense 4B model, and native function calling aligns perfectly with our GBNF-constrained action output.

### 2.2 Qwen 3.5 (Alibaba)

| Property | Value |
|----------|-------|
| **Architecture** | Dense/MoE variants, Gated Delta Networks |
| **Relevant Sizes** | 0.8B, 2B, 4B (dense), 35B-A3B (MoE) |
| **Context Window** | 256K (native!) |
| **Vision** | ✓ Multimodal variants available |
| **Function Calling** | ✓ Supported |
| **Quantized Size (4B, Q4_K_M)** | ~2.8-3.2 GB |
| **VRAM with KV Cache** | ~3.5-4.5 GB |
| **Release Date** | Early 2026 |
| **GGUF Available** | ✓ via llama.cpp / Ollama |
| **Ollama** | `ollama run qwen3.5:4b` |

**Strengths**:
- Massive native context window (256K) — useful for complex state descriptions
- Multiple size options (can use 2B for speed, 4B for accuracy)
- Excellent agentic capabilities in benchmarks
- Mature ecosystem with extensive fine-tuning support

**Weaknesses**:
- Dense 4B model has less reasoning capacity than Gemma 4 E4B (MoE)
- The 35B-A3B MoE variant might be too large for 6GB
- Less optimized for edge devices compared to Gemma 4 E4B

**Verdict for OmniVLA**: ✅ **Strong alternative**. Use Qwen 3.5-4B if Gemma 4 E4B proves unreliable, or use Qwen 3.5-2B for maximum speed when reasoning complexity is low.

### 2.3 Comparison Matrix

| Feature | Gemma 4 E4B | Qwen 3.5-4B | Qwen 3.5-2B |
|---------|------------|------------|------------|
| Active Parameters | 4B (MoE) | 4B (dense) | 2B (dense) |
| VRAM (Q4_K_M + 2K ctx) | ~5.2 GB | ~4.0 GB | ~2.8 GB |
| Reasoning Quality | ⭐⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐ |
| Speed (tokens/s) | ~25-35 | ~30-40 | ~50-70 |
| Function Calling | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐ |
| Context Window | 8K | 256K | 256K |
| Edge Optimization | ⭐⭐⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐⭐ |
| Community/Tooling | ⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ |

### 2.4 Recommendation

```
PRIMARY:   Gemma 4 E4B (Q4_K_M)   — Best reasoning, native function calling
FALLBACK:  Qwen 3.5-4B (Q4_K_M)   — If Gemma proves unreliable
SPEED:     Qwen 3.5-2B (Q4_K_M)   — For latency-critical tasks
```

---

## 3. Quantization Guide

### 3.1 Quantization Formats

| Format | Bits | Size Reduction | Quality Loss | Recommendation |
|--------|------|---------------|-------------|---------------|
| **F16** | 16 | 1x (baseline) | 0% | Too large for 6GB |
| **Q8_0** | 8 | 2x | <1% | Marginal fit, reduced context |
| **Q6_K** | 6 | 2.7x | ~1% | Good quality, tight fit |
| **Q5_K_M** | 5 | 3.2x | ~2% | Good balance |
| **Q4_K_M** | 4 | 4x | ~3% | ✅ **Best for 6GB** |
| **Q4_K_S** | 4 | 4x | ~4% | Slightly smaller than Q4_K_M |
| **Q3_K_M** | 3 | 5.3x | ~5-8% | If Q4 is too large |
| **Q2_K** | 2 | 8x | ~15%+ | Unacceptable quality loss |

**Q4_K_M** is the sweet spot: it reduces model size by 4x with only ~3% quality degradation. This is where most of the SOTA local deployment happens.

### 3.2 Getting GGUF Models

```bash
# Option 1: Ollama (simplest)
ollama pull gemma4:e4b-q4_k_m

# Option 2: Download from HuggingFace
# Search for: "gemma-4-e4b GGUF" or "qwen3.5-4b GGUF"
# Recommended sources: bartowski, unsloth, mradermacher

# Option 3: Quantize yourself
pip install llama-cpp-python
python -m llama_cpp.convert --outtype q4_k_m model.safetensors
```

---

## 4. Inference Server Configuration

### 4.1 llama.cpp Server

```bash
# Start llama.cpp server with optimal settings for 6GB VRAM
./llama-server \
    --model gemma-4-e4b-q4_k_m.gguf \
    --n-gpu-layers -1 \           # Offload ALL layers to GPU
    --ctx-size 2048 \              # Context window (balance vs VRAM)
    --batch-size 512 \             # Batch size for prompt processing
    --n-predict 512 \              # Max generation tokens
    --port 8080 \                  # API port
    --host 127.0.0.1 \            # Local only (security)
    --flash-attn \                # Flash attention (faster, less VRAM)
    --mmap \                      # Memory-map model file
    --threads 4 \                 # CPU threads for KV cache ops
    --cont-batching                # Continuous batching
```

### 4.2 Ollama Configuration

```bash
# Set environment for optimal 6GB VRAM usage
set OLLAMA_FLASH_ATTENTION=1
set OLLAMA_NUM_GPU=999           # Use all GPU layers

# Create a custom modelfile for OmniVLA
cat > Modelfile << 'EOF'
FROM gemma4:e4b-q4_k_m

PARAMETER num_ctx 2048
PARAMETER temperature 0.2
PARAMETER top_p 0.9
PARAMETER repeat_penalty 1.1
PARAMETER num_predict 512

SYSTEM """You are a GUI automation agent operating on Windows..."""
EOF

ollama create omnivla -f Modelfile
ollama run omnivla
```

### 4.3 API Integration

```python
class LLMClient:
    """Client for local LLM inference via llama.cpp or Ollama API."""
    
    def __init__(self, base_url="http://127.0.0.1:8080"):
        self.base_url = base_url
    
    def chat(self, messages, grammar=None, 
             max_tokens=512, temperature=0.2) -> str:
        """Send a chat completion request."""
        payload = {
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": False,
        }
        
        if grammar:
            payload["grammar"] = grammar  # GBNF grammar constraint
        
        response = requests.post(
            f"{self.base_url}/v1/chat/completions",
            json=payload,
            timeout=30
        )
        
        return response.json()["choices"][0]["message"]["content"]
    
    def health_check(self) -> bool:
        """Check if the LLM server is running."""
        try:
            r = requests.get(f"{self.base_url}/health", timeout=5)
            return r.status_code == 200
        except:
            return False
```

---

## 5. VRAM Optimization Techniques

### 5.1 KV Cache Quantization

The KV cache can consume significant VRAM at longer context lengths:

```
KV Cache VRAM = 2 × n_layers × n_heads × head_dim × ctx_length × bytes_per_element

For Gemma 4 E4B (Q4_K_M) at 2048 context:
  ~600-800 MB in FP16
  ~300-400 MB with Q8 KV cache quantization (llama.cpp supports this)
```

Enable KV cache quantization:
```bash
./llama-server --cache-type-k q8_0 --cache-type-v q8_0 ...
```

This saves ~300-400MB of VRAM with minimal quality impact.

### 5.2 Context Window Tuning

Our architecture is designed to use minimal context. Typical usage:

```
System prompt:     ~150 tokens
User prompt:       ~220 tokens  (state + goal + memory)
Generation:        ~50 tokens   (THINK + ACTION)
────────────────────────────────
Total:             ~420 tokens

Context window:    2048 tokens (conservative, VRAM-friendly)
```

We're using only ~20% of our 2048-token context window. This means:
- KV cache VRAM is minimal
- We could reduce context to 1024 to save even more VRAM
- Or increase to 4096 if we need richer state descriptions

### 5.3 Flash Attention

Flash Attention reduces VRAM usage for attention computation:
- **Without Flash Attention**: O(n²) memory for attention matrix
- **With Flash Attention**: O(n) memory — massive savings at long context

Both `llama.cpp` and `vllm` support Flash Attention. Always enable it.

### 5.4 VRAM Monitoring

```python
import subprocess
import re

def get_vram_usage() -> dict:
    """Get current GPU VRAM usage."""
    result = subprocess.run(
        ["nvidia-smi", "--query-gpu=memory.used,memory.total,memory.free",
         "--format=csv,noheader,nounits"],
        capture_output=True, text=True
    )
    
    used, total, free = [int(x.strip()) for x in result.stdout.split(",")]
    
    return {
        "used_mb": used,
        "total_mb": total,
        "free_mb": free,
        "utilization": used / total * 100
    }
```

---

## 6. Text-Only vs Vision Mode

### 6.1 Why Text-Only is Default

In OmniVLA's architecture, the LLM operates in **text-only mode** by default. Screenshots are processed by the perception engine (CPU), and only a text summary is passed to the LLM.

**Advantages of text-only**:
- No vision encoder VRAM cost (~1-2GB saved)
- Faster inference (no image token processing)
- Smaller context window needed
- Works with any text LLM (not limited to VLMs)

### 6.2 When to Use Vision Mode

Vision mode (passing screenshot to a VLM) should be used ONLY when:
1. UIA + OCR perception completely fails (custom rendering, games)
2. The task requires visual understanding (e.g., "click the blue icon")
3. The user explicitly requests visual grounding

### 6.3 Vision Mode Architecture

If vision mode is needed, we must:
1. **Unload the text LLM** from VRAM
2. **Load a VLM** (e.g., Qwen2.5-VL-2B or Gemma 4 E4B with vision)
3. **Run visual grounding** on the screenshot
4. **Unload the VLM** and re-load the text LLM

This "model swapping" takes ~2-3 seconds but is necessary due to VRAM constraints.

```python
class ModelManager:
    """Manages model loading/unloading for 6GB VRAM constraint."""
    
    def switch_to_vision_model(self):
        """Swap text LLM for VLM."""
        # 1. Unload current model
        requests.post(f"{self.base_url}/v1/model/unload")
        
        # 2. Load VLM
        requests.post(f"{self.base_url}/v1/model/load", json={
            "model": "gemma-4-e4b-vision.gguf",
            "n_gpu_layers": -1,
            "ctx_size": 2048
        })
    
    def switch_to_text_model(self):
        """Swap VLM back to text LLM."""
        requests.post(f"{self.base_url}/v1/model/unload")
        requests.post(f"{self.base_url}/v1/model/load", json={
            "model": "gemma-4-e4b-text.gguf",
            "n_gpu_layers": -1,
            "ctx_size": 2048
        })
```

---

## 7. Fine-Tuning Strategy (Advanced)

### 7.1 When Fine-Tuning Helps

The base model may not be ideal for GUI action selection. Fine-tuning on GUI-specific data can improve:
- Action selection accuracy (matching goal to correct element)
- Understanding of UI-specific terminology
- Preference for keyboard shortcuts
- Correct use of the GBNF-constrained output format

### 7.2 Training Data

| Dataset | Samples | Type |
|---------|---------|------|
| Custom OmniVLA traces | 500+ | (state → goal → action) tuples from real usage |
| ScreenSpot | ~1,200 | GUI grounding (instruction → click point) |
| OmniAct | ~9,800 | Desktop/Web screenshots + actions |
| ShareGPT (reasoning) | ~5,000 | General instruction-following (prevent catastrophic forgetting) |

### 7.3 QLoRA Configuration

```python
# Fine-tune on Kaggle/Colab with QLoRA
training_config = {
    "base_model": "google/gemma-4-e4b",
    "quantization": "4bit",  # NF4
    "lora_rank": 64,
    "lora_alpha": 128,
    "lora_targets": "all",   # Target all linear layers
    "learning_rate": 1e-4,
    "epochs": 3,
    "batch_size": 1,
    "gradient_accumulation": 8,
    "max_length": 2048,
    "bf16": True,
    "dataset_ratio": {
        "gui_actions": 0.4,      # 40% GUI-specific
        "gui_grounding": 0.2,    # 20% visual grounding
        "general_reasoning": 0.4  # 40% general (prevent forgetting)
    }
}
```

### 7.4 Converting Fine-Tuned Model to GGUF

```bash
# After fine-tuning, export to GGUF
python -m llama_cpp.convert_lora_to_gguf \
    --base gemma-4-e4b.gguf \
    --lora fine_tuned_adapter/ \
    --output omnivla-gui-lora.gguf

# Or merge and quantize
python -m llama_cpp.merge_lora \
    --base gemma-4-e4b-fp16.gguf \
    --lora fine_tuned_adapter/ \
    --output omnivla-merged-fp16.gguf

python -m llama_cpp.quantize \
    omnivla-merged-fp16.gguf \
    omnivla-merged-q4_k_m.gguf \
    q4_k_m
```

---

## 8. Inference Performance Benchmarks

### Expected Performance on RTX 4050

| Model | Quantization | Prompt Processing | Generation | Total per Action |
|-------|-------------|-------------------|-----------|-----------------|
| Gemma 4 E4B | Q4_K_M | ~100ms (400 tokens) | ~400-600ms (50 tokens) | ~500-700ms |
| Qwen 3.5-4B | Q4_K_M | ~80ms (400 tokens) | ~350-500ms (50 tokens) | ~430-580ms |
| Qwen 3.5-2B | Q4_K_M | ~50ms (400 tokens) | ~200-350ms (50 tokens) | ~250-400ms |

**Note**: These are estimates. Actual performance depends on GPU clock speed, thermal throttling, and system load.

---

*Document Version: 1.0 | Part 07 of 08*
*See also: [08_Advanced_Strategies_Research](./08_Advanced_Strategies_Research.md) for SOTA integration*
