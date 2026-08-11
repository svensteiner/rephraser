"""Privacy-preserving diagnostics for the native desktop boundary."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import tempfile

from app import __version__

MAX_LOG_BYTES = 1_000_000


def diagnostic_log_path() -> Path:
    local_root = os.getenv("LOCALAPPDATA")
    base = Path(local_root) if local_root else Path(tempfile.gettempdir())
    return base / "LLP" / "EditorialTransformer" / "logs" / "desktop.jsonl"


def write_diagnostic_event(event: str, error: BaseException | None = None) -> Path | None:
    """Append metadata only; exception messages and user text are intentionally excluded."""
    path = diagnostic_log_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() and path.stat().st_size >= MAX_LOG_BYTES:
            rotated = path.with_suffix(".jsonl.1")
            if rotated.exists():
                rotated.unlink()
            path.replace(rotated)
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "version": __version__,
            "event": event,
            "exception_type": type(error).__name__ if error is not None else None,
        }
        with path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(record, ensure_ascii=True) + "\n")
        return path
    except OSError:
        return None
