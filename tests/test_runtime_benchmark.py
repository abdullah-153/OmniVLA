from pathlib import Path
from unittest.mock import patch

import benchmark_runtime


def test_readiness_report_enforces_single_gpu_owner(tmp_path: Path):
    vla = tmp_path / "holo.gguf"
    projector = tmp_path / "mmproj.gguf"
    planner = tmp_path / "qwen.gguf"
    for path in (vla, projector, planner):
        path.write_bytes(b"model")

    with (
        patch.object(benchmark_runtime, "_gpu_facts", return_value={"name": "RTX 4050 Laptop GPU", "memory_total_mib": 6144}),
        patch.object(benchmark_runtime, "_endpoint_facts", return_value={"healthy": False, "status_code": None}),
        patch.object(benchmark_runtime, "cuda_backend_available", return_value=True),
        patch.object(benchmark_runtime, "missing_runtime_dlls", return_value=[]),
        patch.object(benchmark_runtime, "driver_runtime_directory", return_value=tmp_path),
    ):
        report = benchmark_runtime.collect_report(vla, projector, planner)

    assert report["checks"]["gpu_has_six_gib"]
    assert report["checks"]["planner_is_cpu_only"]
    assert report["checks"]["vla_is_single_slot"]
    assert report["checks"]["cuda_backend_loadable"]
    assert report["checks"]["visual_reasoning_enabled"]
    assert report["checks"]["grounding_token_floor_enabled"]
    assert report["ready"]
