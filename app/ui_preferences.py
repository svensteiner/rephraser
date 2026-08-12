"""Small, privacy-preserving preferences for the native desktop interface."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
import tempfile


SCHEMA_VERSION = 1


@dataclass(frozen=True, slots=True)
class UiPreferences:
    """Accessibility preferences; never contains document or user content."""

    large_text: bool = False
    high_contrast: bool = False


def ui_preferences_path() -> Path:
    """Return a per-user writable settings path without requiring admin rights."""
    base = os.getenv("LOCALAPPDATA")
    if base:
        return Path(base) / "LLP" / "EditorialTransformer" / "ui-settings.json"
    return Path(tempfile.gettempdir()) / "LLP" / "EditorialTransformer" / "ui-settings.json"


def load_ui_preferences(path: Path | None = None) -> UiPreferences:
    """Load known boolean settings, falling back safely on malformed files."""
    target = path or ui_preferences_path()
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return UiPreferences()
    if not isinstance(payload, dict) or payload.get("schema_version") != SCHEMA_VERSION:
        return UiPreferences()
    large_text = payload.get("large_text")
    high_contrast = payload.get("high_contrast")
    if not isinstance(large_text, bool) or not isinstance(high_contrast, bool):
        return UiPreferences()
    return UiPreferences(large_text=large_text, high_contrast=high_contrast)


def save_ui_preferences(preferences: UiPreferences, path: Path | None = None) -> Path:
    """Atomically persist only the two non-sensitive accessibility settings."""
    target = path or ui_preferences_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {"schema_version": SCHEMA_VERSION, **asdict(preferences)}
    temporary = target.with_name(f".{target.name}.{os.getpid()}.tmp")
    try:
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, target)
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
    return target
