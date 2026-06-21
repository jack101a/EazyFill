"""Runtime failover mode helpers.

APP_MODE is the boot default. A controller can override it by writing a small
JSON or text file at FAILOVER_MODE_FILE so Node B can change modes without a
container rebuild.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

VALID_APP_MODES = {
    "normal",
    "primary",
    "standby",
    "remote_primary_db",
    "failover_readonly",
    "recovery",
    "emergency",
}


def normalize_mode(value: Any, default: str = "normal") -> str:
    mode = str(value or default).strip().lower()
    return mode if mode in VALID_APP_MODES else default


def public_mode(value: Any, default: str = "normal") -> str:
    mode = normalize_mode(value, default)
    if mode == "normal":
        return "primary"
    if mode == "emergency":
        return "failover_readonly"
    return mode


def mode_file_path() -> Path | None:
    raw = os.getenv("FAILOVER_MODE_FILE", "").strip()
    return Path(raw) if raw else None


def read_mode_file() -> str | None:
    path = mode_file_path()
    if not path or not path.exists():
        return None
    try:
        raw = path.read_text(encoding="utf-8").strip()
        if not raw:
            return None
        if raw.startswith("{"):
            payload = json.loads(raw)
            return normalize_mode(payload.get("mode"), default="")
        return normalize_mode(raw, default="")
    except Exception:
        return None


def get_runtime_mode(default_mode: str = "normal") -> str:
    return read_mode_file() or normalize_mode(default_mode)
