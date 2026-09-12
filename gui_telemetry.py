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
    """Scan and terminate any background process listening on the specified port."""
    import os
    import re
    try:
        out = subprocess.check_output(
            ["netstat", "-ano", "-p", "tcp"],
            stderr=subprocess.DEVNULL,
            timeout=4,
        )
        pids = set()
        own_pid = os.getpid()
        # Match TCP lines: TCP  <local_ip>:<port>  <foreign_ip>:<port>  LISTENING  <pid>
        pattern = re.compile(rf"^\s*TCP\s+\S+:({port})\s+\S+\s+LISTENING\s+(\d+)", re.IGNORECASE)
        for line in out.decode('utf-8', errors='ignore').splitlines():
            match = pattern.match(line)
            if match:
                pid_str = match.group(2)
                if pid_str.isdigit():
                    pid = int(pid_str)
                    if pid > 0 and pid != own_pid:
                        pids.add(pid)
        for pid in pids:
            logging.info(f"Terminating process {pid} listening on port {port}")
            subprocess.run(
                ["taskkill", "/f", "/pid", str(pid)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=5,
                check=False,
            )
    except Exception as e:
        logging.debug("kill_port_owner exception: %s", e)
