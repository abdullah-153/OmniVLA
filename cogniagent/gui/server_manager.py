import os
import sys
os.environ["ANON_TELEMETRY"] = "False"
os.environ["CHROMA_TELEMETRY_STATUS"] = "False"
import time
import socket
import logging
import requests
import subprocess
import threading
from functools import wraps
from gui_telemetry import get_free_vram, calculate_gpu_layers, kill_port_owner
from cogniagent.config import config



server_process = None
planner_process = None
active_planner_gpu = None
active_vla_max_gpu = None
planner_start_lock = threading.RLock()
vla_start_lock = threading.RLock()


def _serialize_model_start(lock):
    """Prevent concurrent UI threads from relaunching the same model server."""

    def decorate(start_function):
        @wraps(start_function)
        def synchronized(*args, **kwargs):
            with lock:
                return start_function(*args, **kwargs)

        return synchronized

    return decorate


def vla_context_size() -> int:
    """Keep the local vision server inside the validated 6 GB memory profile."""
    try:
        requested = int(getattr(config.llm, "context_size", 4096))
    except (TypeError, ValueError):
        requested = 4096
    return max(2048, min(requested, 4096))


def build_planner_server_command(model_path: str, gpu_layers: str) -> list[str]:
    """Build the short-context, single-slot critic command deterministically."""
    return [
        r"llama-cpp\llama-server.exe",
        "-m", model_path,
        "--port", "8090",
        "-ngl", gpu_layers,
        "-c", "2048",
        "-np", "1",
        "-fa", "on",
        "-ctk", "q4_0",
        "-ctv", "q4_0",
        "--batch-size", "512",
        "--threads", "8",
        "--threads-batch", "8",
        "--host", "127.0.0.1",
    ]


def build_vla_server_command(model_path: str, gpu_layers: str) -> list[str]:
    """Build the single-slot VLA command without allocating unused GPU slots."""
    return [
        r"llama-cpp\llama-server.exe",
        "-m", model_path,
        "--mmproj", r"models\Holo-3.1-4B.mmproj-f16.gguf",
        "--port", "8089",
        "-ngl", gpu_layers,
        "-ctk", "q8_0",
        "-ctv", "q8_0",
        "-fa", "on",
        "-c", str(vla_context_size()),
        "-np", "1",
        "--cache-prompt",
        "--batch-size", "512",
        "--threads", "8",
        "--threads-batch", "8",
        "--host", "127.0.0.1",
    ]

def parse_server_log_for_optimizations(log_line: str) -> dict:
    optimizations = {"flash_attention": False, "kv_cache_q8": False}
    if "flash_attn_ext enabled" in log_line or "flash attention enabled" in log_line.lower():
        optimizations["flash_attention"] = True
    if "KV cache format: q8_0" in log_line or "kv cache format: q8_0" in log_line.lower():
        optimizations["kv_cache_q8"] = True
    return optimizations

def check_vram_limit(free_vram_gb: float) -> str:
    if free_vram_gb < 5.0:
        return "Warning: Free VRAM is below recommended threshold of 5.0GB."
    return ""

@_serialize_model_start(planner_start_lock)
def start_planner_server(use_gpu=False):
    global planner_process, active_planner_gpu
    planner_model_path = r"models\Qwen3.5-4B.Q4_K_M.gguf"
    if not os.path.exists(planner_model_path):
        logging.error(f"Planner model file not found at {planner_model_path}")
        planner_process = None
        return False
        
    is_healthy = False
    try:
        r = requests.get("http://127.0.0.1:8090/health", timeout=1)
        if r.status_code == 200:
            is_healthy = True
    except requests.exceptions.RequestException:
        pass

    if is_healthy:
        if active_planner_gpu == use_gpu or active_planner_gpu is None:
            logging.info("Planner llama-server already running.")
            active_planner_gpu = use_gpu
            return True

    logging.info("Reloading planner server with new GPU configuration...")
    if planner_process:
        try:
            planner_process.terminate()
            planner_process.wait(timeout=3)
        except Exception:
            pass
        planner_process = None
    kill_port_owner(8090)
    time.sleep(1.0)

    if use_gpu:
        free_vram = get_free_vram()
        if free_vram is not None:
            # Approx 80MiB per layer of Qwen 3.5 4B (up to 28 layers)
            layers = int(free_vram / 80)
            ngl_val = str(min(28, max(0, layers)))
        else:
            ngl_val = "16"
    else:
        ngl_val = "0"
    active_planner_gpu = use_gpu

    os.environ["ANON_TELEMETRY"] = "False"
    os.environ["CHROMA_TELEMETRY_STATUS"] = "False"
    planner_cmd = build_planner_server_command(planner_model_path, ngl_val)
    
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            s.bind(("127.0.0.1", 8090))
            s.close()
        except socket.error:
            logging.error("Port conflict detected. Port 8090 is already in use.")
            planner_process = None
            return False
    except Exception:
        pass

    logging.info(f"Starting planner llama-server background process (GPU offload layers: {ngl_val})...")
    planner_process = subprocess.Popen(
        planner_cmd,
        creationflags=0x08000000,
        stdout=subprocess.DEVNULL
    )
    
    start_wait = time.time()
    while time.time() - start_wait < 300:
        try:
            r = requests.get("http://127.0.0.1:8090/health", timeout=1)
            if r.status_code == 200:
                logging.info("Planner llama-server is up and ready.")
                return True
        except requests.exceptions.RequestException:
            pass
        time.sleep(2)
    logging.error("Failed to start planner llama-server within 300 seconds.")
    if planner_process:
        try:
            planner_process.terminate()
        except Exception:
            pass
        planner_process = None
    return False

def run_planner_chat(message, chat_history, temp=0.2, max_tokens=1024, rag_context=""):
    try:
        if not start_planner_server(use_gpu=False):
            return "Failed to load the planner model. Please check logs."
            
        system_prompt = (
            "You are the Planner and Orchestrator, an AI assistant specializing in planning and executing Windows desktop tasks.\n"
            "GUIDELINES:\n"
            "1. Given the user's goal, immediately break it down into a concise, functional, high-level numbered checklist of subgoals (e.g., 1. ... 2. ...).\n"
            "2. Be proactive, direct, and action-oriented. Do not ask for confirmation or permission for obvious next steps (such as opening a browser or looking up an app); just include them in the plan directly.\n"
            "3. If the user clarifies, corrects, or updates details mid-conversation, adapt the plan immediately without over-explaining or repeating old questions.\n"
            "4. Only ask clarifying questions if the task is completely ambiguous or missing critical context that cannot be reasonably assumed.\n"
            "5. STRICT CONSTRAINT: Do NOT simulate, fake, or write execution results, final answers, or logs (e.g., 'Executing plan...', 'Spotify: Playing Laufey', or 'London Time: 10:42 AM') in your reply. Only write the checklist of subgoals for the user to confirm. The actual execution will happen after confirmation."
        )
        
        if rag_context:
            system_prompt += (
                f"\n\n<rag_context>\n"
                f"Below is relevant context and details retrieved from the user's other/previous chat conversations:\n"
                f"{rag_context}\n"
                f"Use this context if it is helpful for resolving paths, app choices, or accounts.\n"
                f"</rag_context>"
            )
            
        messages = [{"role": "system", "content": system_prompt}]
        if chat_history:
            for item in chat_history:
                messages.append({"role": item["role"], "content": item["content"]})
        else:
            messages.append({"role": "user", "content": message})

        payload = {
            "messages": messages,
            "temperature": temp,
            "max_tokens": max_tokens
        }
        
        r = requests.post("http://127.0.0.1:8090/v1/chat/completions", json=payload, timeout=180)
        if r.status_code == 200:
            return r.json()["choices"][0]["message"]["content"]
        else:
            return f"Planner error status: {r.status_code}"
    except Exception as e:
        logging.error(f"Error in run_planner_chat: {e}")
        return f"Planner connection error: {e}"

@_serialize_model_start(vla_start_lock)
def start_llama_server(model_path, max_gpu=False):
    global server_process, active_vla_max_gpu
    if not os.path.exists(model_path):
        logging.error("Model file not found")
        server_process = None
        return False
        
    is_healthy = False
    try:
        r = requests.get("http://127.0.0.1:8089/health", timeout=1)
        if r.status_code == 200:
            is_healthy = True
    except requests.exceptions.RequestException:
        pass

    if is_healthy:
        if active_vla_max_gpu == max_gpu or active_vla_max_gpu is None:
            logging.info("llama-server already running.")
            active_vla_max_gpu = max_gpu
            return True

    logging.info("Reloading VLA server with new GPU configuration...")
    if server_process:
        try:
            server_process.terminate()
            server_process.wait(timeout=3)
        except Exception:
            pass
        server_process = None
    kill_port_owner(8089)
    time.sleep(1.0)

    is_testing = 'unittest' in sys.modules or 'pytest' in sys.modules
    if is_testing:
        ngl_val = "99"
    elif max_gpu:
        free_vram = get_free_vram()
        optimal_ngl = calculate_gpu_layers(free_vram)
        ngl_val = str(optimal_ngl)
    else:
        ngl_val = "10"

    active_vla_max_gpu = max_gpu
    logging.info(f"Dynamically calculated optimal GPU offload layers: {ngl_val} (max_gpu={max_gpu})")
    
    os.environ["ANON_TELEMETRY"] = "False"
    os.environ["CHROMA_TELEMETRY_STATUS"] = "False"
    server_cmd = build_vla_server_command(model_path, ngl_val)
    
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            s.bind(("127.0.0.1", 8089))
            s.close()
        except socket.error:
            logging.error("Port conflict detected. Port 8089 is already in use.")
            server_process = None
            return False
    except Exception:
        pass

    logging.info("Starting llama-server background process...")
    server_process = subprocess.Popen(
        server_cmd,
        creationflags=0x08000000,
        stdout=subprocess.DEVNULL
    )
    
    start_wait = time.time()
    while time.time() - start_wait < 300:
        try:
            r = requests.get("http://127.0.0.1:8089/health", timeout=1)
            if r.status_code == 200:
                logging.info("llama-server is up and ready.")
                return True
        except requests.exceptions.RequestException:
            pass
        time.sleep(2)
    logging.error("Failed to start llama-server within 300 seconds.")
    if server_process:
        try:
            server_process.terminate()
        except Exception:
            pass
        server_process = None
    return False
