from __future__ import annotations

import json
from pathlib import Path

from app.ui_preferences import UiPreferences, load_ui_preferences, save_ui_preferences, ui_preferences_path


def test_missing_preferences_use_accessible_defaults(tmp_path: Path) -> None:
    assert load_ui_preferences(tmp_path / "missing.json") == UiPreferences()


def test_preferences_round_trip_contains_only_non_sensitive_keys(tmp_path: Path) -> None:
    path = tmp_path / "settings" / "ui.json"
    expected = UiPreferences(large_text=True, high_contrast=True)

    assert save_ui_preferences(expected, path) == path
    assert load_ui_preferences(path) == expected
    assert json.loads(path.read_text(encoding="utf-8")) == {
        "schema_version": 1,
        "large_text": True,
        "high_contrast": True,
    }
    assert not list(path.parent.glob("*.tmp"))


def test_malformed_or_unknown_preferences_are_ignored(tmp_path: Path) -> None:
    path = tmp_path / "ui.json"
    for content in (
        "not json",
        "[]",
        '{"schema_version": 999, "large_text": true, "high_contrast": true}',
        '{"schema_version": 1, "large_text": "yes", "high_contrast": true}',
    ):
        path.write_text(content, encoding="utf-8")
        assert load_ui_preferences(path) == UiPreferences()


def test_default_path_is_per_user_and_contains_no_document_name(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    path = ui_preferences_path()
    assert path == tmp_path / "LLP" / "EditorialTransformer" / "ui-settings.json"
    assert "document" not in str(path).lower()
