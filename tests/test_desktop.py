from app.desktop import (
    MODE_AUTOMATIC,
    MODE_SAFE,
    MODE_STRONG,
    available_modes,
    local_mistral_ready,
    primary_action_label,
    processing_settings,
    request_is_current,
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


def test_late_worker_results_are_rejected_after_fallback_or_close() -> None:
    assert request_is_current(4, 4) is True
    assert request_is_current(3, 4) is False
    assert request_is_current(4, 4, closed=True) is False


def test_safe_result_action_invalidates_slow_model_and_starts_fast_editor(monkeypatch) -> None:
    from app.desktop import DesktopApp

    configured: list[dict[str, object]] = []
    started_with: list[tuple[object, ...]] = []

    class Widget:
        def configure(self, **values):
            configured.append(values)

    class Input:
        def get(self, start, end):
            return "Ein unveränderter Text."

    class ImmediateThread:
        def __init__(self, *, target, args, **kwargs):
            started_with.append(args)

        def start(self):
            return None

    app = DesktopApp.__new__(DesktopApp)
    app.busy = True
    app.processing_active = True
    app.active_request_id = 7
    app.mistral_ready = True
    app.input_text = Input()
    app.run_button = Widget()
    app.result_status = Widget()
    app._worker = object()
    monkeypatch.setattr("app.desktop.threading.Thread", ImmediateThread)

    app.use_safe_result_now()

    assert app.active_request_id == 8
    assert app.processing_active is False
    assert started_with == [("Ein unveränderter Text.", "fast-editor", "medium", 8)]
    assert any(item.get("text") == "Sichere lokale Fassung wird sofort erstellt …" for item in configured)
