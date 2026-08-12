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


def test_review_choice_replaces_output_and_keeps_generated_version_recoverable() -> None:
    from app.desktop import DesktopApp

    class TextBox:
        value = "Verbesserung"

        def delete(self, start, end):
            self.value = ""

        def insert(self, start, text):
            self.value = text

    class Widget:
        def __init__(self):
            self.values = {}

        def configure(self, **values):
            self.values.update(values)

    class Window:
        destroyed = False

        def destroy(self):
            self.destroyed = True

    app = DesktopApp.__new__(DesktopApp)
    app.output_text = TextBox()
    app.copy_button = Widget()
    app.changes_button = Widget()
    app.result_status = Widget()
    app.generated_result = "Verbesserung"
    app.processed_source = "Original"
    window = Window()

    app._use_reviewed_text("Original", window, improved=False)

    assert app.output_text.value == "Original"
    assert app.generated_result == "Verbesserung"
    assert app.copy_button.values["state"] == "normal"
    assert app.changes_button.values["state"] == "normal"
    assert app.result_status.values["text"] == "Original ausgewählt – bereit zum Kopieren."
    assert window.destroyed is True


def test_worker_results_are_queued_without_calling_tk_from_background_thread() -> None:
    import queue
    from app.desktop import DesktopApp

    class Root:
        def after(self, *args):
            raise AssertionError("background worker must not call Tk")

    app = DesktopApp.__new__(DesktopApp)
    app.closed = False
    app.root = Root()
    app.ui_events = queue.Queue()
    callback = object()

    app._schedule_ui(callback, "result", 4)

    assert app.ui_events.get_nowait() == (callback, ("result", 4))


def test_ui_queue_is_drained_on_main_thread() -> None:
    import queue
    from app.desktop import DesktopApp

    scheduled = []
    received = []

    class Root:
        def after(self, delay, callback):
            scheduled.append((delay, callback))

    app = DesktopApp.__new__(DesktopApp)
    app.closed = False
    app.root = Root()
    app.ui_events = queue.Queue()
    app.ui_events.put((lambda *args: received.append(args), ("fertig", 9)))

    app._drain_ui_events()

    assert received == [("fertig", 9)]
    assert scheduled[0][0] == 50


def test_copy_support_info_uses_metadata_report_only() -> None:
    from app.desktop import DesktopApp

    clipboard = []

    class Root:
        def clipboard_clear(self):
            clipboard.clear()

        def clipboard_append(self, value):
            clipboard.append(value)

        def update_idletasks(self):
            return None

    class Button:
        values = {}

        def configure(self, **values):
            self.values.update(values)

    app = DesktopApp.__new__(DesktopApp)
    app.root = Root()
    app.support_text = lambda: "Version 1.7.1\nkein Eingabetext"
    button = Button()

    app._copy_support_info(button)

    assert clipboard == ["Version 1.7.1\nkein Eingabetext"]
    assert button.values["text"] == "Kopiert ✓"


def test_individual_change_selection_is_revalidated_and_applied() -> None:
    from app.change_preview import build_change_segments
    from app.desktop import DesktopApp
    from app.models import TransformOptions
    from app.pipeline import run_pipeline

    class TextBox:
        value = ""

        def delete(self, start, end):
            self.value = ""

        def insert(self, start, text):
            self.value = text

    class Widget:
        values = {}

        def configure(self, **values):
            self.values.update(values)

    class Window:
        destroyed = False

        def destroy(self):
            self.destroyed = True

    source = "Wir möchten gerne prüfen. Zum jetzigen Zeitpunkt fehlt Beleg 17."
    rewritten = "Wir möchten prüfen. Derzeit fehlt Beleg 17."
    result = run_pipeline(source, TransformOptions(provider="fast-editor"))
    assert result.rewritten_text == rewritten
    app = DesktopApp.__new__(DesktopApp)
    app.last_audit = result.audit
    app.output_text = TextBox()
    app.copy_button = Widget()
    app.result_status = Widget()
    app.messagebox = object()
    window = Window()

    app._apply_individual_changes(
        source,
        build_change_segments(source, rewritten),
        (True, False),
        window,
    )

    assert app.output_text.value == "Wir möchten prüfen. Zum jetzigen Zeitpunkt fehlt Beleg 17."
    assert app.copy_button.values["state"] == "normal"
    assert "Geprüfte Einzelauswahl" in app.result_status.values["text"]
    assert window.destroyed is True


def test_individual_change_selection_with_semantic_warning_is_blocked() -> None:
    from app.change_preview import build_change_segments
    from app.desktop import DesktopApp
    from app.models import TransformOptions
    from app.pipeline import run_pipeline

    warnings = []

    class MessageBox:
        def showwarning(self, title, message, **kwargs):
            warnings.append((title, message))

    class Window:
        destroyed = False

        def destroy(self):
            self.destroyed = True

    class ForbiddenOutput:
        def delete(self, start, end):
            raise AssertionError("unsafe candidate must not be displayed")

    source = "Der Gewinn wird nicht steigen."
    unsafe = "Der Gewinn wird deutlich steigen."
    result = run_pipeline(source, TransformOptions(provider="rules"))
    app = DesktopApp.__new__(DesktopApp)
    app.last_audit = result.audit
    app.messagebox = MessageBox()
    app.output_text = ForbiddenOutput()
    window = Window()

    app._apply_individual_changes(
        source,
        build_change_segments(source, unsafe),
        (True,),
        window,
    )

    assert warnings and warnings[0][0] == "Auswahl nicht übernommen"
    assert "Verneinung" in warnings[0][1]
    assert window.destroyed is False
