"""Where the app keeps its cache, settings and the user's collection."""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

from .config import APP_SLUG


def data_dir() -> Path:
    override = os.environ.get("DC_CHECKLIST_HOME")
    if override:
        base = Path(override)
    elif sys.platform == "win32":
        base = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming") / APP_SLUG
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support" / APP_SLUG
    else:
        base = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share") / APP_SLUG
    base.mkdir(parents=True, exist_ok=True)
    return base


def cache_dir(kind: str) -> Path:
    d = data_dir() / "cache" / kind
    d.mkdir(parents=True, exist_ok=True)
    return d


def default_output_dir() -> Path:
    for candidate in (Path.home() / "Desktop", Path.home() / "Schreibtisch",
                      Path.home() / "Documents", Path.home()):
        if candidate.is_dir():
            return candidate
    return Path.home()


def read_json(name: str, default: Any) -> Any:
    path = data_dir() / name
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return default


def write_json(name: str, value: Any) -> None:
    path = data_dir() / name
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(value, fh, ensure_ascii=False, indent=1)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def clear_cache(kind: str | None = None) -> int:
    """Delete cached files. Returns how many files were removed."""
    root = data_dir() / "cache"
    targets = [root / kind] if kind else [root]
    removed = 0
    for target in targets:
        if not target.exists():
            continue
        for p in sorted(target.rglob("*"), reverse=True):
            try:
                if p.is_file():
                    p.unlink()
                    removed += 1
                else:
                    p.rmdir()
            except OSError:
                pass
    return removed
