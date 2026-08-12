"""Native Windows interface for the portable TextVerbessern application."""

from __future__ import annotations

import json
from pathlib import Path
import sys
import threading
import time

from app.local_runtime import LOCAL_MODEL_MAX_CHARACTERS, local_mistral_ready, local_model_eligible
from app.diagnostics import write_diagnostic_event
from app.models import TransformOptions
from app.pipeline import run_pipeline
from app.providers.base import ProviderError
from app.ui_state import classify_result_state, result_actions_allowed


MODE_AUTOMATIC = "Schnell verbessern (empfohlen)"
MODE_SAFE = "Nur Format bereinigen"
MODE_STRONG = "Gründlich mit Mistral (bis 45 s)"
MAX_CHARACTERS = 2_000_000


def processing_settings(mode: str, mistral_ready: bool) -> tuple[str, str]:
    """Map user-facing choices to safe internal provider settings."""
    if mode == MODE_SAFE or not mistral_ready:
        return ("rules", "light") if mode == MODE_SAFE else ("fast-editor", "medium")
    if mode == MODE_STRONG:
        return "rules+mistral-local", "substantial"
    return "fast-editor", "medium"


def available_modes(mistral_ready: bool) -> tuple[str, ...]:
    """Expose only choices that are actually available on this computer."""
    if not mistral_ready:
        return (MODE_AUTOMATIC, MODE_SAFE)
    return (MODE_AUTOMATIC, MODE_SAFE, MODE_STRONG)


def primary_action_label(mistral_ready: bool) -> str:
    return "Text verbessern"


def result_is_current(source: str, processed_source: str | None, result: str, busy: bool) -> bool:
    """Return whether copy/save actions may use the displayed result."""
    state = classify_result_state(source, processed_source, result, result, busy=busy)
    return result_actions_allowed(state)


def request_is_current(request_id: int, active_request_id: int, closed: bool = False) -> bool:
    """Reject late worker results after fallback, restart, or window close."""
    return not closed and request_id == active_request_id


def run_self_test() -> dict[str, object]:
    """Run a dependency-free functional check suitable for packaged builds."""
    source = "Grüße\u00a0aus Wien – 12,5 % am 3. März 2026."
    result = run_pipeline(source, TransformOptions(provider="rules", rewrite_strength="light"))
    expected = "Grüße aus Wien – 12,5 % am 3. März 2026."
    protected = all(value in result.rewritten_text for value in ("Grüße", "12,5 %", "3. März 2026"))
    fast_source = "We would like to better understand the accounts."
    fast_result = run_pipeline(fast_source, TransformOptions(provider="fast-editor"))
    fast_editor = fast_result.rewritten_text == "We would appreciate clarification on the accounts."
    return {
        "ok": result.rewritten_text == expected and protected and fast_editor,
        "safe_cleanup": result.rewritten_text == expected,
        "protected_values": protected,
        "fast_editor": fast_editor,
        "mistral_available": local_mistral_ready(),
    }


class DesktopApp:
    """A deliberately simple paste, improve, copy desktop workflow."""

    def __init__(self) -> None:
        import tkinter as tk
        from tkinter import filedialog, messagebox, scrolledtext, ttk

        self.tk = tk
        self.filedialog = filedialog
        self.messagebox = messagebox
        self.root = tk.Tk()
        self.root.title("Text verbessern")
        self.root.geometry("940x760")
        self.root.minsize(760, 620)
        self.root.configure(background="#f4f7f5")
        self.mistral_ready = local_mistral_ready()
        self.processed_source: str | None = None
        self.busy = False
        self.processing_active = False
        self.processing_started = 0.0
        self.active_request_id = 0
        self.closed = False
        self.root.protocol("WM_DELETE_WINDOW", self._close)

        style = ttk.Style(self.root)
        style.theme_use("vista" if "vista" in style.theme_names() else style.theme_use())
        style.configure("Title.TLabel", font=("Segoe UI", 22, "bold"), background="#f4f7f5")
        style.configure("Hint.TLabel", font=("Segoe UI", 10), background="#f4f7f5", foreground="#456054")
        style.configure("Status.TLabel", font=("Segoe UI", 10, "bold"), padding=9)
        style.configure("Primary.TButton", font=("Segoe UI", 11, "bold"), padding=(18, 10))
        style.configure("Secondary.TButton", font=("Segoe UI", 10), padding=(12, 8))

        outer = ttk.Frame(self.root, padding=(28, 22, 28, 20))
        outer.pack(fill="both", expand=True)
        ttk.Label(outer, text="Text verbessern", style="Title.TLabel").pack(anchor="w")
        ttk.Label(
            outer,
            text="Text aus Claude oder einer anderen Quelle einfügen – alles wird lokal verarbeitet.",
            style="Hint.TLabel",
        ).pack(anchor="w", pady=(2, 12))

        status_text = (
            "✓ Sofortige Textverbesserung bereit; Mistral ist zusätzlich verfügbar."
            if self.mistral_ready
            else "✓ Sofortige lokale Textverbesserung bereit; Mistral ist optional."
        )
        self.system_status = ttk.Label(outer, text=status_text, style="Status.TLabel")
        self.system_status.pack(fill="x", pady=(0, 12))

        top_line = ttk.Frame(outer)
        top_line.pack(fill="x")
        ttk.Label(top_line, text="Dein Text", font=("Segoe UI", 11, "bold")).pack(side="left")
        ttk.Button(top_line, text="Datei öffnen", command=self.open_file, style="Secondary.TButton").pack(side="right")
        self.paste_button = ttk.Button(
            top_line,
            text="Aus Zwischenablage einfügen",
            command=self.paste_clipboard,
            style="Secondary.TButton",
        )
        self.paste_button.pack(side="right", padx=(0, 8))
        self.input_text = scrolledtext.ScrolledText(outer, height=10, wrap="word", font=("Segoe UI", 11), undo=True)
        self.input_text.pack(fill="both", expand=True, pady=(6, 3))
        self.input_text.bind("<<Modified>>", self._source_changed)
        self.source_count = tk.StringVar(value="0 Wörter · 0 Zeichen")
        ttk.Label(outer, textvariable=self.source_count, style="Hint.TLabel").pack(anchor="e", pady=(0, 8))

        controls = ttk.Frame(outer)
        controls.pack(fill="x", pady=(0, 10))
        ttk.Label(controls, text="Bearbeitung:").pack(side="left")
        self.mode = tk.StringVar(value=MODE_AUTOMATIC)
        self.mode_box = ttk.Combobox(
            controls,
            textvariable=self.mode,
            values=available_modes(self.mistral_ready),
            state="readonly",
            width=28,
        )
        self.mode_box.pack(side="left", padx=(8, 14))
        self.run_button = ttk.Button(
            controls,
            text=primary_action_label(self.mistral_ready),
            command=self.start_processing,
            style="Primary.TButton",
        )
        self.run_button.pack(side="right")
        self.progress = ttk.Progressbar(controls, mode="indeterminate", length=150)
        self.progress.pack(side="right", padx=12)

        self.result_line = ttk.Frame(outer)
        ttk.Label(self.result_line, text="Fertiger Text", font=("Segoe UI", 11, "bold")).pack(side="left")
        self.copy_button = ttk.Button(
            self.result_line, text="Ergebnis kopieren", command=self.copy_result,
            style="Secondary.TButton", state="disabled"
        )
        self.copy_button.pack(side="right")
        self.output_text = scrolledtext.ScrolledText(outer, height=10, wrap="word", font=("Segoe UI", 11), undo=True)
        self.result_visible = False

        self.bottom = ttk.Frame(outer)
        self.bottom.pack(fill="x")
        self.result_status = ttk.Label(
            self.bottom,
            text=f"Text einfügen und auf „{primary_action_label(self.mistral_ready)}“ klicken.",
            style="Hint.TLabel",
        )
        self.result_status.pack(side="left")
        ttk.Button(self.bottom, text="Leeren", command=self.clear_all, style="Secondary.TButton").pack(side="right")
        ttk.Button(self.bottom, text="Speichern", command=self.save_result, style="Secondary.TButton").pack(
            side="right", padx=(0, 8)
        )
        ttk.Label(
            outer,
            text="Tastatur: Strg+Enter verbessern · Strg+Umschalt+C Ergebnis kopieren",
            style="Hint.TLabel",
        ).pack(anchor="e", pady=(8, 0))

        self.root.bind("<Control-Return>", lambda _event: self.start_processing())
        self.root.bind("<Control-Shift-C>", lambda _event: self.copy_result())
        self.input_text.focus_set()

    def _set_source_text(self, content: str) -> None:
        if len(content) > MAX_CHARACTERS:
            self.messagebox.showerror(
                "Text zu lang",
                f"Der Text hat mehr als {MAX_CHARACTERS:,} Zeichen und kann nicht verarbeitet werden.".replace(",", "."),
            )
            return
        self.input_text.delete("1.0", "end")
        self.input_text.insert("1.0", content)
        self.input_text.edit_modified(False)
        self._update_source_state()

    def paste_clipboard(self) -> None:
        try:
            content = self.root.clipboard_get()
        except self.tk.TclError:
            self.messagebox.showinfo("Zwischenablage leer", "In der Zwischenablage wurde kein Text gefunden.")
            return
        self._set_source_text(content)
        self.input_text.focus_set()

    def _source_changed(self, _event: object | None = None) -> None:
        if not self.input_text.edit_modified():
            return
        self.input_text.edit_modified(False)
        self._update_source_state()

    def _update_source_state(self) -> None:
        source = self.input_text.get("1.0", "end-1c")
        self.source_count.set(
            f"{len(source.split()):,} Wörter · {len(source):,} Zeichen".replace(",", ".")
        )
        mistral_for_text = local_model_eligible(source, self.mistral_ready)
        self.mode_box.configure(values=available_modes(mistral_for_text))
        if self.mode.get() == MODE_STRONG and not mistral_for_text:
            self.mode.set(MODE_AUTOMATIC)
            if len(source) > LOCAL_MODEL_MAX_CHARACTERS:
                self.result_status.configure(
                    text=(f"Text über {LOCAL_MODEL_MAX_CHARACTERS:,} Zeichen – schnelle lokale Bearbeitung aktiv."
                          .replace(",", "."))
                )
        if self.processed_source is not None and source != self.processed_source:
            self.copy_button.configure(state="disabled")
            self.result_status.configure(text="Ausgangstext geändert – bitte erneut bearbeiten.")

    def open_file(self) -> None:
        path = self.filedialog.askopenfilename(filetypes=(("Text und Markdown", "*.txt *.md"), ("Alle Dateien", "*.*")))
        if not path:
            return
        try:
            content = Path(path).read_text(encoding="utf-8-sig")
        except (OSError, UnicodeError) as error:
            self.messagebox.showerror("Datei nicht lesbar", f"Die Datei konnte nicht geöffnet werden.\n\n{error}")
            return
        self._set_source_text(content)

    def start_processing(self) -> None:
        if self.busy:
            if self.processing_active:
                self.use_safe_result_now()
            return
        source = self.input_text.get("1.0", "end-1c")
        if not source.strip():
            self.messagebox.showinfo("Text fehlt", "Bitte zuerst einen Text einfügen.")
            self.input_text.focus_set()
            return
        if len(source) > MAX_CHARACTERS:
            self.messagebox.showerror(
                "Text zu lang",
                f"Bitte höchstens {MAX_CHARACTERS:,} Zeichen verwenden.".replace(",", "."),
            )
            return
        self.run_button.configure(state="disabled", text=primary_action_label(self.mistral_ready))
        self.busy = True
        self.copy_button.configure(state="disabled")
        self.input_text.configure(state="disabled")
        self.mode_box.configure(state="disabled")
        provider, strength = processing_settings(self.mode.get(), self.mistral_ready)
        self.progress.start(12)
        self.processing_active = "mistral" in provider
        if self.processing_active:
            self.processing_started = time.monotonic()
            self.run_button.configure(state="normal", text="Sichere Fassung jetzt")
            self._update_elapsed_time()
        else:
            self.result_status.configure(text="Text wird sofort lokal verbessert …")
        self.active_request_id += 1
        request_id = self.active_request_id
        thread = threading.Thread(
            target=self._worker,
            args=(source, provider, strength, request_id),
            daemon=True,
        )
        thread.start()

    def use_safe_result_now(self) -> None:
        """Abandon a slow model result and immediately produce the local fast version."""
        if not self.busy or not self.processing_active:
            return
        source = self.input_text.get("1.0", "end-1c")
        self.active_request_id += 1
        request_id = self.active_request_id
        self.processing_active = False
        self.run_button.configure(state="disabled", text=primary_action_label(self.mistral_ready))
        self.result_status.configure(text="Sichere lokale Fassung wird sofort erstellt …")
        thread = threading.Thread(
            target=self._worker,
            args=(source, "fast-editor", "medium", request_id),
            daemon=True,
            name="safe-editor-fallback",
        )
        thread.start()

    def _update_elapsed_time(self) -> None:
        if not self.processing_active:
            return
        elapsed = int(time.monotonic() - self.processing_started)
        self.result_status.configure(
            text=f"Lokale Überarbeitung läuft … {elapsed} s (höchstens 45 s)"
        )
        self.root.after(1000, self._update_elapsed_time)

    def _worker(self, source: str, provider: str, strength: str, request_id: int) -> None:
        try:
            options = TransformOptions(
                provider=provider,
                rewrite_strength=strength,
                language="auto-detect",
                preserve_citations=True,
                preserve_numbers=True,
                preserve_quotations=True,
            )
            result = run_pipeline(source, options)
        except Exception as error:  # UI boundary: always return control to the user.
            self._schedule_ui(self._show_error, error, request_id)
            return
        self._schedule_ui(self._show_result, result, provider, request_id)

    def _schedule_ui(self, callback: object, *args: object) -> None:
        """Deliver worker results only while the Tk window still exists."""
        if self.closed:
            return
        try:
            self.root.after(0, callback, *args)
        except self.tk.TclError:
            return

    def _show_result(self, result: object, provider: str, request_id: int) -> None:
        if not request_is_current(request_id, self.active_request_id, self.closed):
            return
        self.busy = False
        self.processing_active = False
        self.progress.stop()
        self.run_button.configure(state="normal", text=primary_action_label(self.mistral_ready))
        self.input_text.configure(state="normal")
        self.mode_box.configure(state="readonly")
        rewritten = result.rewritten_text
        source = self.input_text.get("1.0", "end-1c")
        changed = rewritten != source
        if not self.result_visible:
            self.result_line.pack(fill="x", before=self.bottom)
            self.output_text.pack(fill="both", expand=True, pady=(6, 8), before=self.bottom)
            self.result_visible = True
        self.output_text.delete("1.0", "end")
        self.output_text.insert("1.0", rewritten)
        self.processed_source = source
        self.copy_button.configure(state="normal")
        self.copy_button.focus_set()
        warning_kinds = {warning.kind for warning in result.audit.fact_preservation_warnings}
        if "model_input_too_long" in warning_kinds:
            message = "Text war für Mistral zu lang; vollständig lokal schnell bearbeitet."
        elif "provider_timeout" in warning_kinds:
            message = "Mistral hat die Zeitgrenze erreicht; sicher bereinigtes Ergebnis angezeigt."
        elif "provider_unavailable" in warning_kinds:
            message = "Mistral war nicht rechtzeitig verfügbar; sicher bereinigtes Ergebnis angezeigt."
        elif "rewrite_rejected" in warning_kinds:
            message = "Sicher bereinigt; eine unsichere Modellfassung wurde verworfen."
        elif result.audit.fact_preservation_warnings:
            message = f"Fertig – bitte {len(result.audit.fact_preservation_warnings)} Prüfhinweis(e) beachten."
        elif not changed:
            message = "Keine sichere Verbesserung erforderlich – der Text ist unverändert."
        elif "mistral" in provider:
            message = f"Fertig – lokal überarbeitet ({len(result.audit.transformations)} Änderungen)."
        elif provider == "fast-editor":
            message = f"Fertig – sofort lokal verbessert ({len(result.audit.transformations)} Änderungen)."
        else:
            message = "Fertig – Formatierungsartefakte bereinigt; der Text wurde nicht sprachlich umformuliert."
        self.result_status.configure(text=message)

    def _show_error(self, error: Exception, request_id: int) -> None:
        if not request_is_current(request_id, self.active_request_id, self.closed):
            return
        self.busy = False
        self.processing_active = False
        self.progress.stop()
        self.run_button.configure(state="normal", text=primary_action_label(self.mistral_ready))
        self.input_text.configure(state="normal")
        self.mode_box.configure(state="readonly")
        source = self.input_text.get("1.0", "end-1c")
        previous = self.output_text.get("1.0", "end-1c")
        previous_available = result_is_current(source, self.processed_source, previous, False)
        self.copy_button.configure(state="normal" if previous_available else "disabled")
        if isinstance(error, ProviderError):
            write_diagnostic_event("provider_unavailable", error)
            message = "Das lokale Sprachmodell antwortet nicht. Der Text hat diesen PC nicht verlassen."
        else:
            write_diagnostic_event("processing_failed", error)
            message = "Die Bearbeitung konnte nicht abgeschlossen werden. Der eingegebene Text bleibt erhalten."
        if previous_available:
            message += " Das letzte gültige Ergebnis bleibt verfügbar."
        self.result_status.configure(text=message)
        self.messagebox.showerror("Bearbeitung nicht möglich", f"{message}\n\nTechnische Information: {error}")

    def _close(self) -> None:
        """Invalidate pending callbacks before closing the native window."""
        self.closed = True
        self.active_request_id += 1
        self.processing_active = False
        self.root.destroy()

    def copy_result(self) -> None:
        source = self.input_text.get("1.0", "end-1c")
        result = self.output_text.get("1.0", "end-1c")
        if not result_is_current(source, self.processed_source, result, self.busy):
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(result)
        self.root.update_idletasks()
        self.result_status.configure(text="Kopiert ✓")
        self.copy_button.configure(text="Kopiert ✓")
        self.root.after(1600, lambda: self.copy_button.configure(text="Ergebnis kopieren"))

    def save_result(self) -> None:
        source = self.input_text.get("1.0", "end-1c")
        result = self.output_text.get("1.0", "end-1c")
        if not result_is_current(source, self.processed_source, result, self.busy):
            self.messagebox.showinfo(
                "Kein aktuelles Ergebnis",
                "Bitte den aktuellen Ausgangstext zuerst bearbeiten; ein älteres Ergebnis wird nicht gespeichert.",
            )
            return
        path = self.filedialog.asksaveasfilename(
            defaultextension=".txt", filetypes=(("Textdatei", "*.txt"), ("Markdown", "*.md"))
        )
        if not path:
            return
        try:
            Path(path).write_text(result, encoding="utf-8", newline="\n")
        except OSError as error:
            write_diagnostic_event("save_failed", error)
            self.messagebox.showerror("Speichern fehlgeschlagen", str(error))
            return
        self.result_status.configure(text="Gespeichert ✓")

    def clear_all(self) -> None:
        self.input_text.delete("1.0", "end")
        self.output_text.delete("1.0", "end")
        self.copy_button.configure(state="disabled")
        self.copy_button.configure(text="Ergebnis kopieren")
        self.processed_source = None
        if self.result_visible:
            self.result_line.pack_forget()
            self.output_text.pack_forget()
            self.result_visible = False
        self.source_count.set("0 Wörter · 0 Zeichen")
        self.result_status.configure(
            text=f"Text einfügen und auf „{primary_action_label(self.mistral_ready)}“ klicken."
        )
        self.input_text.focus_set()

    def run(self) -> None:
        self.root.mainloop()


def main(argv: list[str] | None = None) -> int:
    arguments = argv if argv is not None else sys.argv[1:]
    if "--self-test" in arguments:
        report = run_self_test()
        print(json.dumps(report, ensure_ascii=False))
        return 0 if report["ok"] else 1
    try:
        DesktopApp().run()
    except Exception as error:
        write_diagnostic_event("desktop_fatal", error)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
