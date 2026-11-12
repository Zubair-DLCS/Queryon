"""Which offline model to use, where to find it, and how to download it."""

from __future__ import annotations

import os
import threading
from dataclasses import dataclass
from pathlib import Path

from .config import models_dirs


@dataclass(frozen=True)
class ModelInfo:
    id: str
    name: str
    filename: str
    url: str
    size_gb: float
    min_ram_gb: int
    license: str
    blurb: str


HF = "https://huggingface.co"

CATALOG: list[ModelInfo] = [
    ModelInfo(
        id="light",
        name="Light — Qwen2.5 1.5B",
        filename="Qwen2.5-1.5B-Instruct-Q4_K_M.gguf",
        url=f"{HF}/bartowski/Qwen2.5-1.5B-Instruct-GGUF/resolve/main/Qwen2.5-1.5B-Instruct-Q4_K_M.gguf",
        size_gb=1.0,
        min_ram_gb=4,
        license="Apache 2.0",
        blurb="For 4–6 GB RAM computers. Fast, simpler answers.",
    ),
    ModelInfo(
        id="standard",
        name="Standard — Llama 3.2 3B",
        filename="Llama-3.2-3B-Instruct-Q4_K_M.gguf",
        url=f"{HF}/bartowski/Llama-3.2-3B-Instruct-GGUF/resolve/main/Llama-3.2-3B-Instruct-Q4_K_M.gguf",
        size_gb=2.0,
        min_ram_gb=8,
        license="Llama 3.2 Community License",
        blurb="Recommended for 8 GB+ RAM. Good chat and rewriting.",
    ),
    ModelInfo(
        id="better",
        name="Better — Qwen2.5 7B",
        filename="Qwen2.5-7B-Instruct-Q4_K_M.gguf",
        url=f"{HF}/bartowski/Qwen2.5-7B-Instruct-GGUF/resolve/main/Qwen2.5-7B-Instruct-Q4_K_M.gguf",
        size_gb=4.7,
        min_ram_gb=16,
        license="Apache 2.0",
        blurb="For 16 GB+ RAM. Best quality, about twice as slow.",
    ),
]

BY_ID = {m.id: m for m in CATALOG}


def total_ram_gb() -> float:
    try:
        import psutil

        return psutil.virtual_memory().total / 1024**3
    except Exception:
        return 8.0


def physical_cores() -> int:
    try:
        import psutil

        return max(1, psutil.cpu_count(logical=False) or os.cpu_count() or 4)
    except Exception:
        return max(1, (os.cpu_count() or 4) // 2)


def recommended_model() -> ModelInfo:
    ram = total_ram_gb()
    # Windows reports a little under the installed amount (e.g. 7.8 for 8 GB).
    return BY_ID["light"] if ram < 7 else BY_ID["standard"]


def find_model_file(info: ModelInfo) -> Path | None:
    for d in models_dirs():
        p = d / info.filename
        if p.exists() and p.stat().st_size > 50 * 1024**2:
            return p
    return None


def download_target(info: ModelInfo) -> Path:
    return models_dirs()[-1] / info.filename


def download_model(info: ModelInfo, progress=None, cancel: threading.Event | None = None) -> Path:
    """Download with resume support. progress(bytes_done, bytes_total)."""
    import requests

    target = download_target(info)
    part = target.with_suffix(target.suffix + ".part")
    done = part.stat().st_size if part.exists() else 0
    headers = {"Range": f"bytes={done}-"} if done else {}
    with requests.get(info.url, headers=headers, stream=True, timeout=30, allow_redirects=True) as r:
        if r.status_code == 416:  # already complete
            part.rename(target)
            return target
        r.raise_for_status()
        if done and r.status_code != 206:  # server ignored the range: restart
            done = 0
        total = int(r.headers.get("Content-Length", 0)) + done
        with open(part, "ab" if done else "wb") as f:
            for chunk in r.iter_content(chunk_size=1024 * 1024):
                if cancel is not None and cancel.is_set():
                    raise InterruptedError("Download cancelled")
                f.write(chunk)
                done += len(chunk)
                if progress:
                    progress(done, total)
    part.replace(target)
    return target
