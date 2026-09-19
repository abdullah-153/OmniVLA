"""Read-only readiness report for OmniVLA's consumer-hardware profile."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import Any

import requests

from cogniagent.gui.server_manager import build_planner_server_command, build_vla_server_command
from cogniagent.runtime.cuda_runtime import cuda_backend_available, driver_runtime_directory, missing_runtime_dlls


ROOT = Path(__file__).resolve().parent
DEFAULT_VLA = ROOT / "models" / "Holo-3.1-4B-abliterated-rdo.Q4_K_M.gguf"
DEFAULT_PROJECTOR = ROOT / "models" / "Holo-3.1-4B.mmproj-f16.gguf"
DEFAULT_PLANNER = (
    ROOT / "models" / "Spark-X2.5-4B-Q4_K_M.gguf"
    if (ROOT / "models" / "Spark-X2.5-4B-Q4_K_M.gguf").exists()
    else ROOT / "models" / "Qwen3.5-4B.Q4_K_M.gguf"
)


def _gpu_facts() -> dict[str, Any]:
    command = [
        "nvidia-smi",
        "--query-gpu=name,memory.total,memory.free,driver_version",
        "--format=csv,noheader,nounits",
    ]
    try:
        line = subprocess.check_output(command, timeout=4).decode("utf-8", errors="replace").splitlines()[0]
        name, total, free, driver = [part.strip() for part in line.split(",", 3)]
        return {"name": name, "memory_total_mib": int(total), "memory_free_mib": int(free), "driver": driver}
    except Exception as error:
        return {"available": False, "error": type(error).__name__}


def _endpoint_facts(port: int) -> dict[str, Any]:
    try:
        response = requests.get(f"http://127.0.0.1:{port}/health", timeout=0.6)
        return {"healthy": response.status_code == 200, "status_code": response.status_code}
    except requests.RequestException:
        return {"healthy": False, "status_code": None}


def _file_facts(path: Path) -> dict[str, Any]:
    return {
        "path": str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path),
        "present": path.is_file(),
        "size_mib": round(path.stat().st_size / (1024 * 1024), 1) if path.is_file() else None,
    }


def collect_report(
    vla_path: Path = DEFAULT_VLA,
    projector_path: Path = DEFAULT_PROJECTOR,
    planner_path: Path = DEFAULT_PLANNER,
) -> dict[str, Any]:
    vla_command = build_vla_server_command(str(vla_path), "99")
    planner_command = build_planner_server_command(str(planner_path), "0")
    gpu = _gpu_facts()
    checks = {
        "gpu_has_six_gib": int(gpu.get("memory_total_mib", 0)) >= 6_000,
        "vla_is_single_slot": vla_command[vla_command.index("-np") + 1] == "1",
        # 6144 is the measured quality-preserving floor: the full native tool
        # catalog and a 1080p observation use roughly 4.3k tokens before the
        # model's private reasoning and response allowance.
        "vla_context_is_bounded": int(vla_command[vla_command.index("-c") + 1]) <= 6144,
        "vla_fit_margin_enabled": "-fit" in vla_command and "-fitt" in vla_command,
        "cuda_backend_loadable": cuda_backend_available(),
        "cuda_runtime_complete": not missing_runtime_dlls() and driver_runtime_directory() is not None,
        "visual_reasoning_enabled": vla_command[vla_command.index("--reasoning") + 1] == "on",
        "grounding_token_floor_enabled": int(vla_command[vla_command.index("--image-min-tokens") + 1]) >= 1024,
        "planner_is_cpu_only": (
            planner_command[planner_command.index("-ngl") + 1] == "0"
            and planner_command[planner_command.index("--device") + 1] == "none"
            and "--no-kv-offload" in planner_command
            and "--no-op-offload" in planner_command
        ),
        "models_present": all(path.is_file() for path in (vla_path, projector_path, planner_path)),
    }
    advisories = []
    if "abliterated" in vla_path.name.lower():
        advisories.append(
            "The configured VLA is an abliterated checkpoint. Prefer an aligned Holo 3.1 4B "
            "quant for supervised desktop operation and rerun task/safety evals before switching."
        )
    if planner_path.name.lower().startswith("qwen3.5-4b"):
        advisories.append(
            "Qwen3.5 4B remains the quality-first CPU planner. Benchmark Qwen3.5 2B as a "
            "latency profile; do not promote it without plan-quality and tool-use evals."
        )
    return {
        "target": "RTX 4050 Laptop GPU 6 GB; visual model on CUDA; planner in system memory",
        "gpu": gpu,
        "models": {
            "vla": _file_facts(vla_path),
            "projector": _file_facts(projector_path),
            "planner": _file_facts(planner_path),
        },
        "services": {"vla_8089": _endpoint_facts(8089), "planner_8090": _endpoint_facts(8090)},
        "checks": checks,
        "advisories": advisories,
        "ready": all(checks.values()),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    args = parser.parse_args()
    report = collect_report()
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print("OmniVLA consumer-hardware readiness")
        print(f"Target: {report['target']}")
        gpu = report["gpu"]
        print(f"Detected GPU: {gpu.get('name', 'unavailable')} ({gpu.get('memory_total_mib', 0)} MiB)")
        for name, passed in report["checks"].items():
            print(f"  {'PASS' if passed else 'FAIL'}  {name.replace('_', ' ')}")
        for advisory in report["advisories"]:
            print(f"  NOTE  {advisory}")
        print(f"Overall: {'ready' if report['ready'] else 'needs attention'}")
    return 0 if report["ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
