import subprocess
import logging

def get_free_vram():
    """Query nvidia-smi for free VRAM in MiB. Returns None if query fails."""
    try:
        output = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=memory.free", "--format=csv,noheader,nounits"],
            creationflags=0x08000000,
            timeout=3,
        ).decode().strip()
        return float(output)
    except Exception:
        return None

def calculate_gpu_layers(free_vram_mib=None):
    """Ensure the VLA model and vision projector are loaded fully on CUDA GPU."""
    return 99


def kill_port_owner(port: int):
    """Deprecated: a port number is not proof of process ownership."""
    logging.warning("Refusing to terminate an unowned listener on port %s; stop owned process handles instead.", port)
    return False
