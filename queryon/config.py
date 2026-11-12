"""Paths and persistent settings."""

from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

from . import APP_NAME

# Documents longer than this are cut (with the student's consent). 4,500 words ~ 8 pages.
MAX_WORDS = 4500


def app_dir() -> Path:
    """Folder the program runs from (next to Queryon.exe when frozen)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def data_dir() -> Path:
    """Per-user folder for settings, cache and downloaded models."""
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
    root = Path(base) / APP_NAME if base else Path.home() / f".{APP_NAME.lower()}"
    override = os.environ.get("QUERYON_DATA_DIR")
    if override:
        root = Path(override)
    root.mkdir(parents=True, exist_ok=True)
    return root


def models_dirs() -> list[Path]:
    """Where model files are looked for. A 'models' folder next to the exe comes first,
    so a teacher can copy models to lab PCs on a USB stick with no internet."""
    user = data_dir() / "models"
    user.mkdir(parents=True, exist_ok=True)
    return [app_dir() / "models", user]


def cache_dir() -> Path:
    d = data_dir() / "cache"
    d.mkdir(parents=True, exist_ok=True)
    return d


@dataclass
class Settings:
    backend: str = "local"            # "local" or "cloud"
    local_model: str = "auto"         # "auto", a catalog id, or "custom"
    custom_model_path: str = ""
    threads: int = 0                  # 0 = automatic
    cloud_base_url: str = "https://generativelanguage.googleapis.com/v1beta/openai/"
    cloud_model: str = "gemini-2.5-flash"
    cloud_api_key: str = ""
    extra: dict = field(default_factory=dict)

    @classmethod
    def path(cls) -> Path:
        return data_dir() / "settings.json"

    @classmethod
    def load(cls) -> "Settings":
        try:
            raw = json.loads(cls.path().read_text(encoding="utf-8"))
            known = {k: v for k, v in raw.items() if k in cls.__dataclass_fields__}
            return cls(**known)
        except Exception:
            return cls()

    def save(self) -> None:
        self.path().write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")
