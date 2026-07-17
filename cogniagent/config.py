import os
from dataclasses import dataclass, field
from typing import List

@dataclass
class PerceptionConfig:
    primary_source: str = "uia"
    ocr_engine: str = "easyocr"
    ocr_language: str = "en"
    ocr_gpu: bool = False
    max_elements: int = 200
    downscale_factor: float = 0.5
    capture_monitor: int = 1
    # Consumer-hardware default: keep only the newest screenshot in the VLM
    # prompt. More visual history increases context pressure and VRAM use.
    visual_context_images: int = 1
    # The existing visual verifier samples large frames rather than allocating
    # full-resolution integer buffers on the CPU.
    max_visual_diff_pixels: int = 250_000
    # Retains the original verification feature while allowing constrained
    # deployments to disable the extra post-action screenshot explicitly.
    visual_verification_enabled: bool = True

@dataclass
class LLMConfig:
    backend: str = "llama_cpp"
    base_url: str = "http://127.0.0.1:8089/v1"
    model: str = "models/Holo-3.1-4B-abliterated-rdo.Q4_K_M.gguf"
    model_type: str = "local"
    api_key: str = ""
    # The local deployment has a 6 GB GPU. A single 4k context slot keeps the
    # Holo vision model fully resident while still leaving room for its mmproj
    # and the quantized KV cache. Conversation compaction keeps long runs
    # within this budget instead of relying on a larger, slower cache.
    context_size: int = 4096
    # An action JSON response is normally well below 200 tokens. Keeping this
    # cap tight prevents an accidental long rationale from dominating latency.
    max_tokens: int = 320
    temperature: float = 0.2
    gpu_layers: int = 99

@dataclass
class ExecutionConfig:
    click_pause: float = 0.3
    typing_interval: float = 0.02
    max_retries: int = 2
    action_timeout: float = 5.0
    use_shortcuts: bool = True
    use_uia_invoke: bool = True

@dataclass
class MemoryConfig:
    enabled: bool = True
    db_path: str = "./omnivla_memory"
    embedding_model: str = "all-MiniLM-L6-v2"
    max_results: int = 3

@dataclass
class SafetyConfig:
    native_input_failsafe: bool = True
    max_steps_per_task: int = 25
    confirm_destructive: bool = True
    max_text_input_characters: int = 5_000
    max_wait_seconds: int = 10
    # Stop a model from trying the same action again after verification has
    # already shown that it had no effect.  A single signature is enough: the
    # next action must be observably different or request human help.
    block_repeated_failed_actions: bool = True
    # A model cannot declare a task successful straight after a failed or
    # unverified interaction.  This makes completion an evidence-based state,
    # rather than a claim in model text.
    require_verified_progress_for_success: bool = True
    # UIA tree traversal is useful for supervised/debug deployments but is
    # deliberately opt-in so the default local path stays lean.
    enable_uia_safety_grounding: bool = False
    banned_shortcuts: List[str] = field(
        default_factory=lambda: [
            "alt+f4",
            "ctrl+alt+delete",
            "ctrl+q",
            "ctrl+shift+delete",
            "ctrl+w",
            "delete",
            "shift+delete",
            "win+l",
            "win+r",
            "win+u",
        ]
    )

@dataclass
class OmniVLAConfig:
    perception: PerceptionConfig = field(default_factory=PerceptionConfig)
    llm: LLMConfig = field(default_factory=LLMConfig)
    execution: ExecutionConfig = field(default_factory=ExecutionConfig)
    memory: MemoryConfig = field(default_factory=MemoryConfig)
    safety: SafetyConfig = field(default_factory=SafetyConfig)

# Global config instance
config = OmniVLAConfig()
