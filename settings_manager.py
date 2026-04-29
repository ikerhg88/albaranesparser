"""Gestion de configuracion de usuario (persistente) para Albaranes Parser."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict

DEFAULT_FILENAME = "config.json"
LEGACY_FILENAME = "user_settings.json"
APP_DIRNAME = "AlbaranesParser"


def settings_path(base_dir: Path) -> Path:
    if os.name == "nt":
        root = os.environ.get("APPDATA") or os.environ.get("LOCALAPPDATA")
        if root:
            return Path(root) / APP_DIRNAME / DEFAULT_FILENAME
    return Path.home() / ".config" / APP_DIRNAME / DEFAULT_FILENAME


def _legacy_settings_path(base_dir: Path) -> Path:
    return base_dir / LEGACY_FILENAME


def load_settings(base_dir: Path) -> Dict[str, Any]:
    path = settings_path(base_dir)
    legacy = _legacy_settings_path(base_dir)
    if not path.exists() and legacy.exists():
        path = legacy
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_settings(base_dir: Path, data: Dict[str, Any]) -> None:
    path = settings_path(base_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
