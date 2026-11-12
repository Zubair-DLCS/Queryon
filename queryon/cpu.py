"""Pick the right llama.cpp build for this processor.

The installer ships two builds of the AI engine: a fast one that needs AVX2
(most PCs since about 2014) and a compatible one for older or budget CPUs
(many Celeron/Pentium laptops). This must run before llama_cpp is imported.
"""

from __future__ import annotations

import os
import sys

from .config import app_dir

PF_AVX2_INSTRUCTIONS_AVAILABLE = 40


def has_avx2() -> bool:
    if sys.platform == "win32":
        try:
            import ctypes

            return bool(ctypes.windll.kernel32.IsProcessorFeaturePresent(PF_AVX2_INSTRUCTIONS_AVAILABLE))
        except Exception:
            return True
    try:
        with open("/proc/cpuinfo", encoding="utf-8") as f:
            return " avx2" in f.read()
    except OSError:
        return True


def select_llama_build() -> str:
    """Returns 'fast', 'compatible', or 'default' (running from source)."""
    if "LLAMA_CPP_LIB_PATH" in os.environ:
        return "custom"
    compat = app_dir() / "llama_compat"
    if not compat.exists():
        return "default"
    if has_avx2() and not os.environ.get("QUERYON_FORCE_COMPAT"):
        return "fast"
    os.environ["LLAMA_CPP_LIB_PATH"] = str(compat)
    return "compatible"
