import os
from dataclasses import dataclass, field
from typing import List

@dataclass
class PerceptionConfig:
    primary_source: str = "vlm"
    capture_monitor: int = 1
    # Consumer-hardware default: keep only the newest screenshot in the VLM
    # prompt. More visual history increases context pressure and VRAM use.
    visual_context_images: int = 1
    # Holo's UI grounding depends on preserving small labels, taskbar state,
    # and control boundaries. 720p is the validated accuracy floor; reducing
    # this to 768x432 caused false icon detections and coarse click locations.
    screenshot_max_width: int = 1920
    screenshot_max_height: int = 1080
    screenshot_jpeg_quality: int = 90
    # The visual verifier samples large frames rather than allocating
    # full-resolution integer buffers on the CPU.
    max_visual_diff_pixels: int = 250_000
    visual_verification_enabled: bool = True

@dataclass
class LLMConfig:
    backend: str = "llama_cpp"
    base_url: str = "http://127.0.0.1:8089/v1"
    planner_url: str = "http://127.0.0.1:8090/v1"
    model: str = "models/Holo-3.1-4B-abliterated-rdo.Q4_K_M.gguf"
    planner_model: str = "models/Qwen3.5-4B.Q4_K_M.gguf"
    model_type: str = "local"
    api_key: str = ""
    context_size: int = 4096
    # Includes the model's private reasoning plus one native tool call.
    # This is a ceiling, not a forced generation length.
    max_tokens: int = 384
    temperature: float = 0.2
    gpu_layers: int = 99

@dataclass
class ExecutionConfig:
    click_pause: float = 0.3
    typing_interval: float = 0.02
    max_retries: int = 2
    action_timeout: float = 5.0
    use_shortcuts: bool = True

@dataclass
class MemoryConfig:
    enabled: bool = True
    db_path: str = "./omnivla_memory_v2"
    embedding_model: str = "all-MiniLM-L6-v2"
    max_results: int = 3

@dataclass
class SkillsConfig:
    enabled: bool = True
    skills_dir: str = "./skills"
    auto_generate: bool = True
    min_confidence_to_execute: float = 0.85

@dataclass
class SafetyConfig:
    native_input_failsafe: bool = True
    # A hard safety ceiling. Each run derives a smaller budget from the
    # reviewed plan and expands it only while verified progress continues.
    max_steps_per_task: int = 60
    confirm_destructive: bool = True
    max_text_input_characters: int = 5_000
    max_wait_seconds: int = 10
    # Stop a model from trying the same action again after verification has
    # already shown that it had no effect.
    block_repeated_failed_actions: bool = True
    # A model cannot declare a task successful straight after a failed or
    # unverified interaction.
    require_verified_progress_for_success: bool = True
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
    skills: SkillsConfig = field(default_factory=SkillsConfig)
    safety: SafetyConfig = field(default_factory=SafetyConfig)

# Global config instance
config = OmniVLAConfig()
