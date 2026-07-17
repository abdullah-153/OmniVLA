import subprocess
import logging

def get_free_vram():
    """Query nvidia-smi for free VRAM in MiB. Returns None if query fails."""
    try:
        output = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=memory.free", "--format=csv,noheader,nounits"],
            creationflags=0x08000000
        ).decode().strip()
        return float(output)
    except Exception:
        return None

def calculate_gpu_layers(free_vram_mib=None):
    """Ensure the VLA model is loaded fully on the GPU by allocating all 28 layers."""
    return 28

def kill_port_owner(port):
    """Scan and terminate any background process bound to the specified port."""
    import os
    try:
        cmd = f"netstat -ano | findstr :{port}"
        proc = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        out, _ = proc.communicate()
        pids = set()
        own_pid = os.getpid()
        for line in out.decode('utf-8', errors='ignore').strip().split('\n'):
            parts = line.strip().split()
            if len(parts) >= 5:
                pid = parts[-1]
                if pid.isdigit() and int(pid) > 0 and int(pid) != own_pid:
                    pids.add(pid)
        for pid in pids:
            logging.info(f"Terminating process {pid} binding port {port}")
            subprocess.run(f"taskkill /f /pid {pid}", shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass
