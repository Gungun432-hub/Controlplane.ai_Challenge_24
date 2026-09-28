"""Read `.env` at start-up, without a dependency and without surprises.

Three rules, because a config loader that guesses is worse than none:

1. A variable already set in the real environment **always wins**. Exporting
   something in your shell must override the file, never the other way round.
2. Only `KEY=value` lines are read. No interpolation, no command substitution,
   no includes — a config file that can execute is a config file that can be
   weaponised.
3. Nothing is ever logged. The whole point of this file is that it holds
   credentials.

`.env` is gitignored. `.env.example` is the tracked template.
"""
from __future__ import annotations

import os
from pathlib import Path

# repo root: python/controlplane/env.py -> python/controlplane -> python -> root
ROOT = Path(__file__).resolve().parents[2]


def _unquote(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        return value[1:-1]
    # An unquoted trailing comment is a comment; a quoted one is part of the value.
    if " #" in value:
        value = value.split(" #", 1)[0].rstrip()
    return value


def load(path: str | Path | None = None, *, override: bool = False) -> list[str]:
    """Load a dotenv file. Returns the NAMES that were set — never the values."""
    target = Path(path) if path else Path(os.getenv("CONTROLPLANE_ENV_FILE") or ROOT / ".env")
    if not target.is_file():
        return []

    applied: list[str] = []
    try:
        raw = target.read_text(encoding="utf-8")
    except OSError:
        return []

    for line in raw.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.lower().startswith("export "):
            line = line[7:]
        key, _, value = line.partition("=")
        key = key.strip()
        if not key or not key.replace("_", "").isalnum():
            continue
        if not override and key in os.environ:
            continue
        os.environ[key] = _unquote(value)
        applied.append(key)
    return applied
