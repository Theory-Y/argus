"""theory_y.config — resolve base URL + credential from flags / env / config file."""

from __future__ import annotations

import json
import os
from pathlib import Path

_CONFIG_PATH = Path.home() / ".theory-y" / "config.json"
_DEFAULT_URL = "http://localhost:8000"


def _read_file() -> dict:
    if _CONFIG_PATH.is_file():
        try:
            return json.loads(_CONFIG_PATH.read_text())
        except json.JSONDecodeError:
            return {}
    return {}


def resolve(url: str | None = None, key: str | None = None) -> tuple[str, str | None]:
    """Precedence: explicit arg → env var → saved config file → default."""
    file_cfg = _read_file()
    resolved_url = (
        url
        or os.environ.get("THEORYY_URL")
        or file_cfg.get("url")
        or _DEFAULT_URL
    )
    resolved_key = (
        key
        or os.environ.get("THEORYY_API_KEY")
        or file_cfg.get("key")
    )
    return resolved_url.rstrip("/"), resolved_key


def save(url: str, key: str | None) -> Path:
    # The file holds a credential — lock it down to the owner. Create with 0o600
    # atomically (not chmod-after-write) and keep the containing dir 0o700, even
    # if it pre-existed.
    _CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(_CONFIG_PATH.parent, 0o700)
    payload = json.dumps({"url": url.rstrip("/"), "key": key}, indent=2)
    fd = os.open(_CONFIG_PATH, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(payload)
    return _CONFIG_PATH
