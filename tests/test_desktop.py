from app.desktop import (
    MODE_AUTOMATIC,
    MODE_SAFE,
    MODE_STRONG,
    available_modes,
    local_mistral_ready,
    primary_action_label,
    processing_settings,
    result_is_current,
    run_self_test,
)


def test_processing_settings_are_safe_without_mistral() -> None:
    assert processing_settings(MODE_AUTOMATIC, False) == ("fast-editor", "medium")
    assert processing_settings(MODE_STRONG, False) == ("fast-editor", "medium")


def test_processing_settings_use_hybrid_only_when_available() -> None:
    assert processing_settings(MODE_AUTOMATIC, True) == ("fast-editor", "medium")
    assert processing_settings(MODE_STRONG, True) == ("rules+mistral-local", "substantial")
    assert processing_settings(MODE_SAFE, True) == ("rules", "light")


def test_desktop_exposes_only_actions_that_are_really_available() -> None:
    assert available_modes(False) == (MODE_AUTOMATIC, MODE_SAFE)
    assert primary_action_label(False) == "Text verbessern"
    assert available_modes(True) == (MODE_AUTOMATIC, MODE_SAFE, MODE_STRONG)
    assert primary_action_label(True) == "Text verbessern"


def test_desktop_self_test_preserves_german_values() -> None:
    report = run_self_test()
    assert report["ok"] is True
    assert report["safe_cleanup"] is True
    assert report["protected_values"] is True
    assert report["fast_editor"] is True


def test_readiness_check_refuses_non_loopback_hostname(monkeypatch) -> None:
    monkeypatch.setenv("MISTRAL_BASE_URL", "http://localhost.evil.example:11434")
    assert local_mistral_ready() is False


def test_readiness_check_refuses_userinfo(monkeypatch) -> None:
    monkeypatch.setenv("MISTRAL_BASE_URL", "http://user@localhost:11434")
    assert local_mistral_ready() is False


def test_result_actions_require_current_non_busy_output() -> None:
    assert result_is_current("source", "source", "result", False) is True
    assert result_is_current("changed", "source", "result", False) is False
    assert result_is_current("source", "source", "result", True) is False
    assert result_is_current("source", None, "result", False) is False
    assert result_is_current("source", "source", "", False) is False
