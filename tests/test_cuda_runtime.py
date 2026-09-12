import hashlib
import io
import os
from pathlib import Path
from unittest.mock import patch
import zipfile

from cogniagent.runtime import cuda_runtime


def _runtime_archive() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as bundle:
        bundle.writestr("bin/cublas64_13.dll", b"cublas")
        bundle.writestr("bin/cublasLt64_13.dll", b"cublas-lt")
    return buffer.getvalue()


def test_missing_runtime_dlls_reports_only_absent_files(tmp_path: Path):
    (tmp_path / "cublas64_13.dll").write_bytes(b"present")
    assert cuda_runtime.missing_runtime_dlls(tmp_path) == ["cublasLt64_13.dll"]


def test_cuda_server_environment_prepends_driver_directory(tmp_path: Path):
    with patch.object(cuda_runtime, "driver_runtime_directory", return_value=tmp_path):
        environment = cuda_runtime.cuda_server_environment()

    assert environment is not None
    assert environment["PATH"].split(os.pathsep)[0] == str(tmp_path)


def test_ensure_cuda_runtime_verifies_and_extracts_pinned_members(tmp_path: Path):
    archive = _runtime_archive()
    asset = {
        "url": "https://example.invalid/cuda.zip",
        "sha256": hashlib.sha256(archive).hexdigest(),
        "members": cuda_runtime.REQUIRED_DLLS,
    }

    with (
        patch.object(cuda_runtime, "CUDA_ASSETS", (asset,)),
        patch.object(cuda_runtime.urllib.request, "urlopen", return_value=io.BytesIO(archive)),
    ):
        assert cuda_runtime.ensure_cuda_runtime(tmp_path)

    assert (tmp_path / "cublas64_13.dll").read_bytes() == b"cublas"
    assert (tmp_path / "cublasLt64_13.dll").read_bytes() == b"cublas-lt"
    assert not list(tmp_path.glob("*.part"))


def test_ensure_cuda_runtime_rejects_unverified_archive(tmp_path: Path):
    asset = {
        "url": "https://example.invalid/cuda.zip",
        "sha256": "0" * 64,
        "members": cuda_runtime.REQUIRED_DLLS,
    }
    with (
        patch.object(cuda_runtime, "CUDA_ASSETS", (asset,)),
        patch.object(cuda_runtime.urllib.request, "urlopen", return_value=io.BytesIO(_runtime_archive())),
    ):
        assert not cuda_runtime.ensure_cuda_runtime(tmp_path)

    assert cuda_runtime.missing_runtime_dlls(tmp_path) == list(cuda_runtime.REQUIRED_DLLS)
