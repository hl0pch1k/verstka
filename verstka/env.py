"""Minimal .env loader: KEY=VALUE lines, no dependency. Existing environment variables always win."""

from __future__ import annotations

import os
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_loaded = False


def parse_env(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export "):].lstrip()
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if not key or not key.replace("_", "").isalnum():
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        elif " #" in value:
            value = value.split(" #", 1)[0].rstrip()
        out[key] = value
    return out


def load_env(paths: list[Path] | None = None, force: bool = False) -> list[Path]:
    """Load .env from the current directory and the repo root (first wins); never overrides real env vars.

    VERSTKA_NO_DOTENV=1 skips the implicit files (the test suite sets it: tests never pick up a real API key)."""
    global _loaded
    if _loaded and not force and paths is None:
        return []
    if paths is None and os.environ.get("VERSTKA_NO_DOTENV"):
        return []
    _loaded = True
    used: list[Path] = []
    for path in paths or [Path.cwd() / ".env", _REPO_ROOT / ".env"]:
        try:
            if not path.is_file():
                continue
            values = parse_env(path.read_text(encoding="utf-8"))
        except OSError:
            continue
        for key, value in values.items():
            if value and not os.environ.get(key):
                os.environ[key] = value
        used.append(path)
    return used
