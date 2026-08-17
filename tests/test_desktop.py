from app.desktop import (
    CLIPBOARD_UNAVAILABLE_MESSAGE,
    KEYBOARD_SHORTCUTS,
    MODE_AUTOMATIC,
    MODE_SAFE,
    MODE_STRONG,
    ProcessingRequest,
    STARTUP_ERROR_MESSAGE,
    STARTUP_ERROR_TITLE,
    available_modes,
    local_mistral_ready,
    primary_action_label,
    processing_settings,
    request_is_current,
    RELEASE_PAGE_URL,
    result_is_current,
    run_self_test,
    show_startup_error,
    system_status_text,
)


def test_keyboard_shortcuts_cover_complete_mouse_free_workflow() -> None:
    assert KEYBOARD_SHORTCUTS == {
        "F1": "Info & Hilfe",
        "Strg+O": "Datei öffnen",
        "Strg+Umschalt+V": "Zwischenablage einfügen",
        "Strg+Enter": "Text verbessern",
        "Strg+E": "Ergebnis bearbeiten / prüfen",
        "Escape": "Sichere Fassung / manuelle Änderungen verwerfen",
        "Strg+Umschalt+C": "Ergebnis kopieren",
    }


def test_shortcut_handler_runs_action_and_stops_default_event() -> None:
    from app.desktop import DesktopApp

    bindings = {}
    called = []

    class Root:
        def bind(self, sequence, handler):
            bindings[sequence] = handler

    app = DesktopApp.__new__(DesktopApp)
    app.root = Root()
    app._bind_shortcut("<F1>", lambda: called.append("help"))

    assert bindings["<F1>"](object()) == "break"
    assert called == ["help"]


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


def test_native_startup_error_is_private_and_windows_only(monkeypatch) -> None:
    from app import desktop

    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(desktop.sys, "platform", "win32")
    monkeypatch.setattr(
        desktop,
        "_show_native_startup_dialog",
        lambda title, message: calls.append((title, message)),
    )

    assert show_startup_error() is True
    assert calls == [(STARTUP_ERROR_TITLE, STARTUP_ERROR_MESSAGE)]
    assert "kein eingegebener Text" in STARTUP_ERROR_MESSAGE
    assert "RuntimeError" not in STARTUP_ERROR_MESSAGE

    monkeypatch.setattr(desktop.sys, "platform", "linux")
    assert show_startup_error() is False
    assert len(calls) == 1


def test_fatal_desktop_startup_is_logged_and_shown_without_error_details(monkeypatch) -> None:
    from app import desktop

    events: list[tuple[str, BaseException]] = []
    shown: list[bool] = []

    class BrokenDesktopApp:
        def __init__(self) -> None:
            raise RuntimeError("VERTRAULICHER MANDANTENTEXT")

    monkeypatch.setattr(desktop, "DesktopApp", BrokenDesktopApp)
    monkeypatch.setattr(desktop, "write_diagnostic_event", lambda event, error: events.append((event, error)))
    monkeypatch.setattr(desktop, "show_startup_error", lambda: shown.append(True) or True)

    assert desktop.main([]) == 1
    assert [event for event, _ in events] == ["desktop_fatal"]
    assert isinstance(events[0][1], RuntimeError)
    assert shown == [True]


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


def test_request_identity_requires_the_same_immutable_source_snapshot() -> None:
    request = ProcessingRequest(4, "Ursprünglicher Text")

    assert request_is_current(request, request, current_source="Ursprünglicher Text") is True
    assert request_is_current(request, ProcessingRequest(4, "Neuer Text")) is False
    assert request_is_current(request, request, current_source="Neuer Text") is False


def test_clear_cancels_active_worker_and_rejects_its_late_result_or_error(monkeypatch) -> None:
    from app.desktop import DesktopApp
    from app.pipeline import run_pipeline

    class Widget:
        def __init__(self) -> None:
            self.values: dict[str, object] = {}
            self.stopped = False
            self.hidden = False
            self.focused = False

        def configure(self, **values: object) -> None:
            self.values.update(values)

        def stop(self) -> None:
            self.stopped = True

        def pack_forget(self) -> None:
            self.hidden = True

        def focus_set(self) -> None:
            self.focused = True

    class TextBox(Widget):
        def __init__(self, text: str) -> None:
            super().__init__()
            self.text = text

        def get(self, _start: str, _end: str) -> str:
            return self.text

        def delete(self, _start: str, _end: str) -> None:
            self.text = ""

        def insert(self, _start: str, text: str) -> None:
            self.text = text

        def edit_modified(self, _value: bool) -> None:
            return None

    class Value:
        def __init__(self) -> None:
            self.value = ""

        def set(self, value: str) -> None:
            self.value = value

    class MessageBox:
        def __init__(self) -> None:
            self.errors: list[tuple[str, str]] = []

        def showerror(self, title: str, message: str) -> None:
            self.errors.append((title, message))

    class Root:
        def __init__(self) -> None:
            self.clipboard: list[str] = []

        def clipboard_clear(self) -> None:
            self.clipboard.clear()

        def clipboard_append(self, text: str) -> None:
            self.clipboard.append(text)

        def update_idletasks(self) -> None:
            return None

    app = DesktopApp.__new__(DesktopApp)
    request = ProcessingRequest(12, "Vertraulicher Ausgangstext")
    app.active_request_id = request.request_id
    app.active_request = request
    app.closed = False
    app.busy = True
    app.processing_active = True
    app.processing_started = 123.0
    app.model_request_inflight_id = request.request_id
    app.mistral_ready = True
    app.input_text = TextBox(request.source)
    app.output_text = TextBox("Altes Ergebnis")
    app.run_button = Widget()
    app.mode_box = Widget()
    app.protected_terms_button = Widget()
    app.progress = Widget()
    app.copy_button = Widget()
    app.changes_button = Widget()
    app.edit_result_button = Widget()
    app.discard_edit_button = Widget()
    app.result_status = Widget()
    app.result_line = Widget()
    app.bottom = Widget()
    app.source_count = Value()
    app.result_visible = True
    app.output_editing = False
    app.processed_source = request.source
    app.generated_result = "Altes Ergebnis"
    app.last_audit = object()
    app.manual_result_verified = True
    app.verified_result_before_edit = "Altes Ergebnis"
    app.protected_terms = ("Ausgangstext",)
    app.messagebox = MessageBox()
    app.root = Root()
    app._refresh_mistral_controls = lambda: None
    app._update_protected_terms_button = lambda: None
    diagnostic_events: list[str] = []
    monkeypatch.setattr(
        "app.desktop.write_diagnostic_event", lambda event, _error: diagnostic_events.append(event)
    )

    app.clear_all()

    assert app.active_request is None
    assert app.active_request_id == 13
    assert app.busy is False
    assert app.processing_active is False
    assert app.progress.stopped is True
    assert app.input_text.text == ""
    assert app.output_text.text == ""
    assert app.copy_button.values["state"] == "disabled"
    # Keep this marker until the abandoned Mistral worker has actually ended.
    assert app.model_request_inflight_id == request.request_id

    app._show_result(run_pipeline(request.source), "rules", request)
    app._show_error(RuntimeError("später Workerfehler"), request)
    app.copy_result()

    assert app.output_text.text == ""
    assert app.generated_result == ""
    assert app.manual_result_verified is False
    assert app.messagebox.errors == []
    assert diagnostic_events == []
    assert app.root.clipboard == []


def test_safe_result_action_invalidates_slow_model_and_starts_rules_cleanup(monkeypatch) -> None:
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
    app.model_request_inflight_id = 7
    app.input_text = Input()
    app.run_button = Widget()
    app.result_status = Widget()
    app.protected_terms = ()
    app._worker = object()
    monkeypatch.setattr("app.desktop.threading.Thread", ImmediateThread)

    app.use_safe_result_now()

    assert app.active_request_id == 8
    assert app.processing_active is False
    assert started_with == [(
        "Ein unveränderter Text.",
        "rules",
        "light",
        ProcessingRequest(8, "Ein unveränderter Text."),
        (),
        "user_selected_safe_fallback",
    )]
    assert any(item.get("text") == "Sichere lokale Fassung wird sofort erstellt …" for item in configured)


def test_thorough_mode_preflight_immediately_uses_rules_when_mistral_stopped(monkeypatch) -> None:
    from app.desktop import DesktopApp

    started_with: list[tuple[object, ...]] = []

    class Widget:
        def __init__(self):
            self.values: dict[str, object] = {}

        def configure(self, **values):
            self.values.update(values)

        def focus_set(self):
            self.values["focused"] = True

    class Input(Widget):
        def get(self, start, end):
            return "Ein klarer Text."

    class Mode:
        def __init__(self, value):
            self.value = value

        def get(self):
            return self.value

        def set(self, value):
            self.value = value

    class Progress:
        def start(self, interval):
            return None

    class Root:
        def update_idletasks(self):
            return None

    class ImmediateThread:
        def __init__(self, *, target, args, **kwargs):
            started_with.append(args)

        def start(self):
            return None

    app = DesktopApp.__new__(DesktopApp)
    app.busy = False
    app.processing_active = False
    app.active_request_id = 0
    app.model_request_inflight_id = None
    app.mistral_ready = True
    app.manual_result_verified = True
    app.protected_terms = ()
    app.mode = Mode(MODE_STRONG)
    app.input_text = Input()
    app.mode_box = Widget()
    app.run_button = Widget()
    app.copy_button = Widget()
    app.protected_terms_button = Widget()
    app.result_status = Widget()
    app.system_status = Widget()
    app.progress = Progress()
    app.root = Root()
    app.tk = type("Tk", (), {"TclError": RuntimeError})
    monkeypatch.setattr("app.desktop.preflight_local_mistral", lambda: False)
    monkeypatch.setattr("app.desktop.threading.Thread", ImmediateThread)

    app.start_processing()

    assert started_with == [(
        "Ein klarer Text.",
        "rules",
        "light",
        ProcessingRequest(1, "Ein klarer Text."),
        (),
        "provider_unavailable",
    )]
    assert app.mistral_ready is False
    assert app.mode.get() == MODE_AUTOMATIC
    assert app.mode_box.values["values"] == available_modes(False)
    assert "derzeit nicht erreichbar" in app.result_status.values["text"]
    assert "optional" in app.system_status.values["text"]


def test_thorough_mode_preflight_keeps_model_path_when_local_model_is_ready(monkeypatch) -> None:
    from app.desktop import DesktopApp

    started_with: list[tuple[object, ...]] = []

    class Widget:
        def __init__(self):
            self.values: dict[str, object] = {}

        def configure(self, **values):
            self.values.update(values)

        def focus_set(self):
            self.values["focused"] = True

    class Input(Widget):
        def get(self, start, end):
            return "Ein klarer Text."

    class Mode:
        def get(self):
            return MODE_STRONG

        def set(self, value):
            raise AssertionError(f"unexpected mode change: {value}")

    class Progress:
        def start(self, interval):
            return None

    class Root:
        def update_idletasks(self):
            return None

    class ImmediateThread:
        def __init__(self, *, target, args, **kwargs):
            started_with.append(args)

        def start(self):
            return None

    app = DesktopApp.__new__(DesktopApp)
    app.busy = False
    app.processing_active = False
    app.active_request_id = 0
    app.model_request_inflight_id = None
    app.mistral_ready = True
    app.manual_result_verified = True
    app.protected_terms = ()
    app.mode = Mode()
    app.input_text = Input()
    app.mode_box = Widget()
    app.run_button = Widget()
    app.copy_button = Widget()
    app.protected_terms_button = Widget()
    app.result_status = Widget()
    app.progress = Progress()
    app.root = Root()
    app.tk = type("Tk", (), {"TclError": RuntimeError})
    app._update_elapsed_time = lambda: None
    monkeypatch.setattr("app.desktop.preflight_local_mistral", lambda: True)
    monkeypatch.setattr("app.desktop.threading.Thread", ImmediateThread)

    app.start_processing()

    assert started_with == [(
        "Ein klarer Text.",
        "rules+mistral-local",
        "substantial",
        ProcessingRequest(1, "Ein klarer Text."),
        (),
        None,
    )]
    assert app.model_request_inflight_id == 1
    assert app.run_button.values["text"] == "Sichere Fassung jetzt"
    assert app.run_button.values["focused"] is True


def test_thorough_mode_stays_hidden_until_abandoned_model_worker_finishes() -> None:
    from app.desktop import DesktopApp

    class Widget:
        def __init__(self):
            self.values: dict[str, object] = {}

        def configure(self, **values):
            self.values.update(values)

    class Input:
        def get(self, start, end):
            return "Ein klarer Text."

    class Mode:
        def __init__(self):
            self.value = MODE_AUTOMATIC

        def get(self):
            return self.value

        def set(self, value):
            self.value = value

    app = DesktopApp.__new__(DesktopApp)
    app.mistral_ready = True
    app.model_request_inflight_id = 4
    app.input_text = Input()
    app.mode = Mode()
    app.mode_box = Widget()
    app.system_status = Widget()

    app._refresh_mistral_controls()
    assert app.mode_box.values["values"] == available_modes(False)
    app._model_request_finished(4)
    assert app.model_request_inflight_id is None
    assert app.mode_box.values["values"] == available_modes(True)
    assert "zusätzlich verfügbar" in app.system_status.values["text"]


def test_provider_unavailable_result_hides_stale_thorough_mode(monkeypatch) -> None:
    from app.desktop import DesktopApp
    from app.models import ValidationWarning
    from app.pipeline import run_pipeline

    class Widget:
        def __init__(self):
            self.values: dict[str, object] = {}

        def configure(self, **values):
            self.values.update(values)

        def focus_set(self):
            self.values["focused"] = True

        def pack(self, **values):
            return None

        def stop(self):
            return None

    class TextBox(Widget):
        def __init__(self, text):
            super().__init__()
            self.text = text

        def get(self, start, end):
            return self.text

        def delete(self, start, end):
            self.text = ""

        def insert(self, start, text):
            self.text = text

        def edit_modified(self, value):
            return None

    class Mode:
        def __init__(self):
            self.value = MODE_AUTOMATIC

        def get(self):
            return self.value

        def set(self, value):
            self.value = value

    result = run_pipeline("Ein klarer Text.")
    result.audit.fact_preservation_warnings.append(ValidationWarning(
        kind="provider_unavailable", severity="medium", value="connection_refused", message="unavailable"
    ))
    app = DesktopApp.__new__(DesktopApp)
    app.active_request_id = 3
    app.closed = False
    app.mistral_ready = True
    app.model_request_inflight_id = None
    app.busy = True
    app.processing_active = True
    app.progress = Widget()
    app.run_button = Widget()
    app.input_text = TextBox("Ein klarer Text.")
    app.mode = Mode()
    app.mode_box = Widget()
    app.protected_terms_button = Widget()
    app.system_status = Widget()
    app.result_line = Widget()
    app.bottom = Widget()
    app.output_text = TextBox("")
    app.result_visible = True
    app.copy_button = Widget()
    app.changes_button = Widget()
    app.edit_result_button = Widget()
    app.discard_edit_button = Widget()
    app.result_status = Widget()

    app._show_result(result, "rules", 3)

    assert app.mistral_ready is False
    assert app.mode_box.values["values"] == available_modes(False)
    assert "optional" in app.system_status.values["text"]
    assert "nicht verfügbar" in app.result_status.values["text"]


def test_escape_uses_safe_fallback_only_while_model_processing() -> None:
    from app.desktop import DesktopApp

    called = []
    app = DesktopApp.__new__(DesktopApp)
    app.busy = True
    app.processing_active = True
    app.output_editing = False
    app.use_safe_result_now = lambda: called.append("safe")
    app.discard_manual_edits = lambda: called.append("discard")

    app._handle_escape()

    assert called == ["safe"]


def test_ui_watchdog_automatically_uses_safe_result_at_deadline(monkeypatch) -> None:
    from app.desktop import DesktopApp, MODEL_UI_DEADLINE_SECONDS

    called = []
    app = DesktopApp.__new__(DesktopApp)
    app.processing_active = True
    app.processing_started = 100.0
    app.use_safe_result_now = lambda *, automatically=False: called.append(automatically)
    monkeypatch.setattr("app.desktop.time.monotonic", lambda: 100.0 + MODEL_UI_DEADLINE_SECONDS)

    app._update_elapsed_time()

    assert called == [True]


def test_ui_watchdog_keeps_counting_before_deadline(monkeypatch) -> None:
    from app.desktop import DesktopApp

    configured = []
    scheduled = []

    class Widget:
        def configure(self, **values):
            configured.append(values)

    class Root:
        def after(self, delay, callback):
            scheduled.append((delay, callback))

    app = DesktopApp.__new__(DesktopApp)
    app.processing_active = True
    app.processing_started = 100.0
    app.result_status = Widget()
    app.root = Root()
    monkeypatch.setattr("app.desktop.time.monotonic", lambda: 144.9)

    app._update_elapsed_time()

    assert configured[-1]["text"] == "Lokale Überarbeitung läuft … 44 s (höchstens 45 s)"
    assert scheduled[0][0] == 1000


def test_timeout_fallback_is_recorded_in_audit() -> None:
    from app.desktop import DesktopApp

    scheduled = []
    app = DesktopApp.__new__(DesktopApp)
    app._schedule_ui = lambda callback, *args: scheduled.append(args)

    app._worker("Ein klarer Text.", "rules", "light", 9, (), "provider_timeout")

    result, provider, request_id = scheduled[0]
    assert provider == "rules"
    assert request_id == 9
    assert result.audit.requested_provider == "rules+mistral-local"
    assert result.audit.options["provider"] == "rules"
    assert result.audit.options["rewrite_strength"] == "light"
    assert result.audit.options["requested_provider"] == "rules+mistral-local"
    assert result.audit.options["requested_rewrite_strength"] == "substantial"
    assert result.audit.options["fallback_reason"] == "provider_timeout"
    assert result.audit.applied_provider == "rules"
    assert any(w.kind == "provider_timeout" for w in result.audit.fact_preservation_warnings)


def test_system_status_mentions_only_currently_available_model_actions() -> None:
    assert "zusätzlich verfügbar" in system_status_text(True)
    assert "optional" in system_status_text(False)
    assert "frühere Anfrage" in system_status_text(True, model_request_inflight=True)


def test_review_choice_replaces_output_and_keeps_generated_version_recoverable() -> None:
    from app.desktop import DesktopApp

    class TextBox:
        value = "Verbesserung"

        def configure(self, **values):
            return None

        def delete(self, start, end):
            self.value = ""

        def insert(self, start, text):
            self.value = text

        def edit_modified(self, value):
            return None

    class Widget:
        def __init__(self):
            self.values = {}
            self.focused = False

        def configure(self, **values):
            self.values.update(values)

        def focus_set(self):
            self.focused = True

    class Window:
        destroyed = False

        def destroy(self):
            self.destroyed = True

    app = DesktopApp.__new__(DesktopApp)
    app.output_text = TextBox()
    app.copy_button = Widget()
    app.changes_button = Widget()
    app.edit_result_button = Widget()
    app.discard_edit_button = Widget()
    app.result_status = Widget()
    app.generated_result = "Verbesserung"
    app.processed_source = "Original"
    window = Window()

    app._use_reviewed_text("Original", window, improved=False)

    assert app.output_text.value == "Original"
    assert app.generated_result == "Verbesserung"
    assert app.copy_button.values["state"] == "normal"
    assert app.copy_button.focused is True
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


def test_ui_queue_continues_after_callback_failure_and_reschedules_privately(monkeypatch) -> None:
    import queue
    from app.desktop import DesktopApp

    scheduled = []
    received = []
    diagnostics = []

    class Root:
        def after(self, delay, callback):
            scheduled.append((delay, callback))

    def failing_callback(*_args):
        raise RuntimeError("VERTRAULICHER EINGABETEXT")

    def record_diagnostic(event, error):
        diagnostics.append((event, type(error).__name__))

    monkeypatch.setattr("app.desktop.write_diagnostic_event", record_diagnostic)
    app = DesktopApp.__new__(DesktopApp)
    app.closed = False
    app.root = Root()
    app.ui_events = queue.Queue()
    app.ui_events.put((failing_callback, ("ignored",)))
    app.ui_events.put((lambda *args: received.append(args), ("weiter", 10)))

    app._drain_ui_events()

    assert received == [("weiter", 10)]
    assert diagnostics == [("ui_callback_failed", "RuntimeError")]
    assert scheduled and scheduled[0][0] == 50


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


def test_copy_support_info_reports_clipboard_failure_without_exposing_diagnostics(monkeypatch) -> None:
    from app.desktop import DesktopApp

    diagnostics = []
    messages = []

    class Root:
        def clipboard_clear(self):
            return None

        def clipboard_append(self, _value):
            raise RuntimeError("Clipboard has confidential data")

        def update_idletasks(self):
            raise AssertionError("clipboard append must stop the copy operation")

    class Button:
        def __init__(self):
            self.values = {}

        def configure(self, **values):
            self.values.update(values)

    class MessageBox:
        def showwarning(self, title, message):
            messages.append((title, message))

    def record_diagnostic(event, error):
        diagnostics.append((event, type(error).__name__))

    monkeypatch.setattr("app.desktop.write_diagnostic_event", record_diagnostic)
    app = DesktopApp.__new__(DesktopApp)
    app.root = Root()
    app.messagebox = MessageBox()
    app.support_text = lambda: "Version 1.7.1\\nkein Eingabetext"
    button = Button()

    app._copy_support_info(button)

    assert diagnostics == [("clipboard_copy_failed", "RuntimeError")]
    assert button.values["text"] == "Kopieren nicht möglich"
    assert messages == [("Kopieren nicht möglich", CLIPBOARD_UNAVAILABLE_MESSAGE)]
    assert "confidential" not in messages[0][1]


def test_copy_result_reports_clipboard_failure_without_exposing_text(monkeypatch) -> None:
    from app.desktop import DesktopApp

    diagnostics = []
    messages = []

    class Text:
        def __init__(self, value):
            self.value = value

        def get(self, _start, _end):
            return self.value

    class Root:
        def clipboard_clear(self):
            raise RuntimeError("VERTRAULICHER AUSGABETEXT")

        def clipboard_append(self, _value):
            raise AssertionError("clipboard append must not run after clear failed")

        def update_idletasks(self):
            raise AssertionError("clipboard update must not run after clear failed")

        def after(self, *_args):
            raise AssertionError("a failed copy must not schedule a success reset")

    class Widget:
        def __init__(self):
            self.values = {}

        def configure(self, **values):
            self.values.update(values)

    class MessageBox:
        def showwarning(self, title, message):
            messages.append((title, message))

    def record_diagnostic(event, error):
        diagnostics.append((event, type(error).__name__))

    source = "Ausgangstext"
    result = "Vertrauliches Ergebnis"
    monkeypatch.setattr("app.desktop.write_diagnostic_event", record_diagnostic)
    app = DesktopApp.__new__(DesktopApp)
    app.input_text = Text(source)
    app.output_text = Text(result)
    app.processed_source = source
    app.busy = False
    app.manual_result_verified = True
    app.root = Root()
    app.result_status = Widget()
    app.copy_button = Widget()
    app.messagebox = MessageBox()

    app.copy_result()

    assert diagnostics == [("clipboard_copy_failed", "RuntimeError")]
    assert app.result_status.values["text"] == CLIPBOARD_UNAVAILABLE_MESSAGE
    assert app.copy_button.values["text"] == "Kopieren nicht möglich"
    assert messages == [("Kopieren nicht möglich", CLIPBOARD_UNAVAILABLE_MESSAGE)]
    assert result not in messages[0][1]


def test_release_page_opens_only_when_user_invokes_action(monkeypatch) -> None:
    from app.desktop import DesktopApp

    opened = []
    app = DesktopApp.__new__(DesktopApp)
    app.messagebox = object()
    monkeypatch.setattr("app.desktop.webbrowser.open", lambda url, new: opened.append((url, new)) or True)

    app.open_release_page()

    assert opened == [(RELEASE_PAGE_URL, 2)]


def test_release_page_failure_shows_copyable_url(monkeypatch) -> None:
    from app.desktop import DesktopApp

    messages = []

    class MessageBox:
        def showinfo(self, title, message):
            messages.append((title, message))

    app = DesktopApp.__new__(DesktopApp)
    app.messagebox = MessageBox()
    monkeypatch.setattr("app.desktop.webbrowser.open", lambda url, new: False)

    app.open_release_page()

    assert messages == [("GitHub nicht geöffnet", "Bitte diese Adresse im Browser öffnen:\n\n" + RELEASE_PAGE_URL)]


def test_help_window_is_large_enough_for_accessibility_controls() -> None:
    from app.desktop import DesktopApp
    from app.ui_preferences import UiPreferences

    calls = []

    class Window:
        def minsize(self, width, height):
            calls.append(("minsize", width, height))

        def geometry(self, geometry):
            calls.append(("geometry", geometry))

    app = DesktopApp.__new__(DesktopApp)
    app.ui_preferences = UiPreferences(large_text=True, high_contrast=False)
    app._size_help_window(Window())
    assert calls == [("minsize", 700, 650), ("geometry", "700x650")]


def test_individual_change_selection_is_revalidated_and_applied() -> None:
    from app.change_preview import build_change_segments
    from app.desktop import DesktopApp
    from app.models import TransformOptions
    from app.pipeline import run_pipeline

    class TextBox:
        value = ""

        def configure(self, **values):
            return None

        def delete(self, start, end):
            self.value = ""

        def insert(self, start, text):
            self.value = text

        def edit_modified(self, value):
            return None

    class Widget:
        def __init__(self):
            self.values = {}
            self.focused = False

        def configure(self, **values):
            self.values.update(values)

        def focus_set(self):
            self.focused = True

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
    app.edit_result_button = Widget()
    app.discard_edit_button = Widget()
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
    assert app.copy_button.focused is True
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


def test_manual_result_edit_requires_successful_recheck_before_copy() -> None:
    from app.desktop import DesktopApp
    from app.models import TransformOptions
    from app.pipeline import run_pipeline

    class TextBox:
        def __init__(self, value):
            self.value = value
            self.modified = False
            self.state = "disabled"

        def configure(self, **values):
            self.state = values.get("state", self.state)

        def delete(self, start, end):
            self.value = ""

        def insert(self, start, text):
            self.value = text

        def get(self, start, end):
            return self.value

        def edit_modified(self, value=None):
            if value is None:
                return self.modified
            self.modified = value

        def focus_set(self):
            return None

    class Source:
        def get(self, start, end):
            return "Der Betrag bleibt 12,5 %."

    class Widget:
        def __init__(self):
            self.values = {}
            self.focused = False

        def configure(self, **values):
            self.values.update(values)

        def focus_set(self):
            self.focused = True

    source = "Der Betrag bleibt 12,5 %."
    result = run_pipeline(source, TransformOptions(provider="rules"))
    app = DesktopApp.__new__(DesktopApp)
    app.input_text = Source()
    app.output_text = TextBox(source)
    app.processed_source = source
    app.generated_result = source
    app.last_audit = result.audit
    app.output_editing = False
    app.manual_result_verified = True
    app.busy = False
    app.copy_button = Widget()
    app.changes_button = Widget()
    app.edit_result_button = Widget()
    app.discard_edit_button = Widget()
    app.result_status = Widget()

    app.toggle_result_editing()
    assert app.output_editing is True
    assert app.manual_result_verified is False
    assert app.copy_button.values["state"] == "disabled"
    app.output_text.value = "Der Betrag bleibt 12,5 % und ist bestätigt."
    app.toggle_result_editing()

    assert app.output_editing is False
    assert app.manual_result_verified is True
    assert app.output_text.state == "disabled"
    assert app.copy_button.values["state"] == "normal"
    assert app.copy_button.focused is True
    assert "keine Bedeutungs-Garantie" in app.result_status.values["text"]


def test_manual_result_edit_with_missing_protected_value_stays_blocked() -> None:
    from app.desktop import DesktopApp
    from app.models import TransformOptions
    from app.pipeline import run_pipeline

    shown = []

    class TextBox:
        value = "Der Betrag fehlt."

        def get(self, start, end):
            return self.value

    class Source:
        def get(self, start, end):
            return "Der Betrag bleibt 12,5 %."

    class MessageBox:
        def showwarning(self, title, message):
            shown.append((title, message))

    source = "Der Betrag bleibt 12,5 %."
    result = run_pipeline(source, TransformOptions(provider="rules"))
    app = DesktopApp.__new__(DesktopApp)
    app.input_text = Source()
    app.output_text = TextBox()
    app.processed_source = source
    app.last_audit = result.audit
    app.output_editing = True
    app.manual_result_verified = False
    app.busy = False
    app.messagebox = MessageBox()

    app.toggle_result_editing()

    assert app.output_editing is True
    assert app.manual_result_verified is False
    assert shown and shown[0][0] == "Manuelle Fassung noch nicht freigegeben"
    assert "12,5 %" in shown[0][1]


def test_unverified_manual_result_cannot_be_copied_or_reach_save_dialog() -> None:
    from app.desktop import DesktopApp

    infos = []

    class Text:
        def __init__(self, value):
            self.value = value

        def get(self, start, end):
            return self.value

    class Root:
        def clipboard_clear(self):
            raise AssertionError("unverified text must not reach clipboard")

    class FileDialog:
        def asksaveasfilename(self, **kwargs):
            raise AssertionError("unverified text must not reach save dialog")

    class MessageBox:
        def showinfo(self, title, message):
            infos.append((title, message))

    app = DesktopApp.__new__(DesktopApp)
    app.input_text = Text("Quelle")
    app.output_text = Text("Manuell geändert")
    app.processed_source = "Quelle"
    app.busy = False
    app.manual_result_verified = False
    app.root = Root()
    app.filedialog = FileDialog()
    app.messagebox = MessageBox()

    app.copy_result()
    app.save_result()

    assert infos and "ungeprüfte" in infos[0][1]


def test_discard_manual_edits_restores_exact_last_verified_result() -> None:
    from app.desktop import DesktopApp

    class TextBox:
        value = "Beschädigte manuelle Fassung"
        state = "normal"

        def configure(self, **values):
            self.state = values.get("state", self.state)

        def delete(self, start, end):
            self.value = ""

        def insert(self, start, text):
            self.value = text

        def get(self, start, end):
            return self.value

        def edit_modified(self, value):
            return None

    class Source:
        def get(self, start, end):
            return "Quelle 12,5 %."

    class Widget:
        def __init__(self):
            self.values = {}
            self.focused = False

        def configure(self, **values):
            self.values.update(values)

        def focus_set(self):
            self.focused = True

    app = DesktopApp.__new__(DesktopApp)
    app.output_text = TextBox()
    app.input_text = Source()
    app.output_editing = True
    app.manual_result_verified = False
    app.verified_result_before_edit = "Geprüfte Fassung 12,5 %."
    app.generated_result = "Geprüfte Fassung 12,5 %."
    app.copy_button = Widget()
    app.changes_button = Widget()
    app.edit_result_button = Widget()
    app.discard_edit_button = Widget()
    app.result_status = Widget()

    app.discard_manual_edits()

    assert app.output_text.value == "Geprüfte Fassung 12,5 %."
    assert app.output_text.state == "disabled"
    assert app.output_editing is False
    assert app.manual_result_verified is True
    assert app.copy_button.values["state"] == "normal"
    assert app.copy_button.focused is True
    assert app.discard_edit_button.values["state"] == "disabled"
    assert "wiederhergestellt" in app.result_status.values["text"]
