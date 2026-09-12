"""Install and validate the CUDA runtime paired with the bundled llama.cpp.

The repository carries llama.cpp build b8955, whose CUDA backend links against
the CUDA 13.1 portable runtime. The upstream project publishes those DLLs as a
separate signed release asset, so a copied executable can otherwise fall back
to CPU without an obvious error.
"""

from __future__ import annotations

import hashlib
import logging
import os
from pathlib import Path
import shutil
import tempfile
import urllib.request
import zipfile


REQUIRED_DLLS = ("cublas64_13.dll", "cublasLt64_13.dll")
CUDA_ASSETS = (
    {
        "url": (
            "https://github.com/ggml-org/llama.cpp/releases/download/b8955/"
            "cudart-llama-bin-win-cuda-13.1-x64.zip"
        ),
        "sha256": "f96935e7e385e3b2d0189239077c10fe8fd7e95690fea4afec455b1b6c7e3f18",
        "members": ("cublas64_13.dll", "cublasLt64_13.dll"),
    },
)


def runtime_directory() -> Path:
    return Path(__file__).resolve().parents[2] / "llama-cpp"


def missing_runtime_dlls(target: Path | None = None) -> list[str]:
    destination = target or runtime_directory()
    return [name for name in REQUIRED_DLLS if not (destination / name).is_file()]


def driver_runtime_directory() -> Path | None:
    """Locate NVIDIA's driver-matched hybrid CUDA runtime without copying it."""
    windows = Path(os.environ.get("WINDIR", r"C:\Windows"))
    roots = [windows / "System32", windows / "System32" / "DriverStore" / "FileRepository"]
    for root in roots:
        if not root.exists():
            continue
        matches = list(root.glob("nvcudart_hybrid64.dll"))
        if not matches and root.name == "FileRepository":
            matches = list(root.glob("nvhmi.inf_*/*nvcudart_hybrid64.dll"))
        if matches:
            return matches[0].parent
    return None


def cuda_server_environment() -> dict[str, str] | None:
    """Return a narrow child environment that can resolve the NVIDIA driver DLL."""
    driver_directory = driver_runtime_directory()
    if driver_directory is None:
        return None
    environment = dict(os.environ)
    existing = environment.get("PATH", "")
    environment["PATH"] = str(driver_directory) + (os.pathsep + existing if existing else "")
    return environment


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def ensure_cuda_runtime(target: Path | None = None) -> bool:
    """Fetch the pinned official DLL bundle only when dependencies are absent."""
    destination = target or runtime_directory()
    missing = missing_runtime_dlls(destination)
    if not missing:
        return True

    destination.mkdir(parents=True, exist_ok=True)
    logging.warning("CUDA runtime is incomplete; installing %s from the pinned llama.cpp release.", ", ".join(missing))
    try:
        with tempfile.TemporaryDirectory(prefix="omnivla-cuda-") as temp_dir:
            for index, asset in enumerate(CUDA_ASSETS):
                needed = [name for name in asset["members"] if not (destination / name).is_file()]
                if not needed:
                    continue
                archive = Path(temp_dir) / f"cuda-runtime-{index}.zip"
                request = urllib.request.Request(asset["url"], headers={"User-Agent": "OmniVLA-runtime-bootstrap"})
                with urllib.request.urlopen(request, timeout=60) as response, archive.open("wb") as output:
                    shutil.copyfileobj(response, output, length=1024 * 1024)
                if _sha256(archive) != asset["sha256"]:
                    raise RuntimeError("Downloaded CUDA runtime failed its SHA-256 integrity check.")
                with zipfile.ZipFile(archive) as bundle:
                    members = {Path(name).name: name for name in bundle.namelist()}
                    for filename in needed:
                        member = members.get(filename)
                        if not member:
                            raise RuntimeError(f"Official CUDA archive is missing {filename}.")
                        pending = destination / f".{filename}.part"
                        with bundle.open(member) as source, pending.open("wb") as output:
                            shutil.copyfileobj(source, output, length=1024 * 1024)
                        os.replace(pending, destination / filename)
    except Exception as error:
        logging.error("Unable to install the CUDA runtime: %s", error)
        return False
    return not missing_runtime_dlls(destination)


def cuda_backend_available(target: Path | None = None) -> bool:
    """Load the CUDA backend once so CPU fallback cannot masquerade as GPU mode."""
    if os.name != "nt":
        return False
    destination = target or runtime_directory()
    if missing_runtime_dlls(destination):
        return False
    driver_directory = driver_runtime_directory()
    if driver_directory is None:
        return False
    try:
        import ctypes

        with os.add_dll_directory(str(destination)), os.add_dll_directory(str(driver_directory)):
            ctypes.WinDLL(str(destination / "ggml-cuda.dll"), winmode=0x00001500)
        return True
    except (OSError, FileNotFoundError):
        return False
