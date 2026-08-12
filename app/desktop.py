"""Native Windows interface for the portable TextVerbessern application."""

from __future__ import annotations

import json
from pathlib import Path
import queue
import sys
import threading
import time

from app.change_preview import ChangeSegment, apply_change_selection, build_change_preview, build_change_segments
from app.local_runtime import LOCAL_MODEL_MAX_CHARACTERS, local_mistral_ready, local_model_eligible
from app import __version__
from app.diagnostics import diagnostic_log_path, write_diagnostic_event
from app.models import AuditReport, TransformOptions, ValidationWarning
from app.pipeline import run_pipeline
from app.providers.base import ProviderError
from app.protection import missing_protected_terms, normalize_protected_terms
from app.review_summary import build_review_summary
from app.support import build_support_info
from app.ui_preferences import UiPreferences, load_ui_preferences, save_ui_preferences
from app.ui_state import classify_result_state, result_actions_allowed
from app.validation import validate_preservation


MODE_AUTOMATIC = "Schnell verbessern (empfohlen)"
MODE_SAFE = "Nur Format bereinigen"
MODE_STRONG = "Gründlich mit Mistral (bis 45 s)"
MODEL_UI_DEADLINE_SECONDS = 45.0
MAX_CHARACTERS = 2_000_000
CHANGE_PREVIEW_MAX_CHARACTERS = 200_000
INDIVIDUAL_CHANGE_MAX_GROUPS = 100
KEYBOARD_SHORTCUTS = {
    "F1": "Info & Hilfe",
    "Strg+O": "Datei öffnen",
    "Strg+Umschalt+V": "Zwischenablage einfügen",
    "Strg+Enter": "Text verbessern",
    "Strg+E": "Ergebnis bearbeiten / prüfen",
    "Escape": "Manuelle Änderungen verwerfen",
    "Strg+Umschalt+C": "Ergebnis kopieren",
}


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
        import tkinter.font as tkfont
        from tkinter import filedialog, messagebox, scrolledtext, ttk

        self.tk = tk
        self.ttk = ttk
        self.scrolledtext = scrolledtext
        self.filedialog = filedialog
        self.messagebox = messagebox
        self.root = tk.Tk()
        self.ui_preferences = load_ui_preferences()
        self.protected_terms: tuple[str, ...] = ()
        self.root.title("Text verbessern")
        self.root.geometry("940x760")
        self.root.minsize(760, 620)
        self.body_font = tkfont.Font(root=self.root, family="Segoe UI", size=11)
        self.body_bold_font = tkfont.Font(root=self.root, family="Segoe UI", size=11, weight="bold")
        self.title_font = tkfont.Font(root=self.root, family="Segoe UI", size=22, weight="bold")
        self.dialog_title_font = tkfont.Font(root=self.root, family="Segoe UI", size=17, weight="bold")
        self.hint_font = tkfont.Font(root=self.root, family="Segoe UI", size=10)
        self.hint_bold_font = tkfont.Font(root=self.root, family="Segoe UI", size=10, weight="bold")
        self.mono_font = tkfont.Font(root=self.root, family="Consolas", size=9)
        self.mistral_ready = local_mistral_ready()
        self.processed_source: str | None = None
        self.generated_result = ""
        self.last_audit: AuditReport | None = None
        self.output_editing = False
        self.manual_result_verified = False
        self.verified_result_before_edit = ""
        self.busy = False
        self.processing_active = False
        self.processing_started = 0.0
        self.active_request_id = 0
        self.closed = False
        self.ui_events: queue.Queue[tuple[object, tuple[object, ...]]] = queue.Queue()
        self.root.protocol("WM_DELETE_WINDOW", self._close)
        self.root.after(50, self._drain_ui_events)

        self.style = ttk.Style(self.root)
        self.default_theme = "vista" if "vista" in self.style.theme_names() else self.style.theme_use()
        self._apply_view_preferences()

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
        ttk.Label(top_line, text="Dein Text", font=self.body_bold_font).pack(side="left")
        ttk.Button(top_line, text="Datei öffnen", command=self.open_file, style="Secondary.TButton").pack(side="right")
        self.paste_button = ttk.Button(
            top_line,
            text="Aus Zwischenablage einfügen",
            command=self.paste_clipboard,
            style="Secondary.TButton",
        )
        self.paste_button.pack(side="right", padx=(0, 8))
        self.input_text = scrolledtext.ScrolledText(outer, height=10, wrap="word", font=self.body_font, undo=True)
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
        ttk.Label(self.result_line, text="Fertiger Text", font=self.body_bold_font).pack(side="left")
        self.changes_button = ttk.Button(
            self.result_line,
            text="Änderungen ansehen",
            command=self.open_change_preview,
            style="Secondary.TButton",
            state="disabled",
        )
        self.changes_button.pack(side="left", padx=(12, 0))
        self.edit_result_button = ttk.Button(
            self.result_line,
            text="Ergebnis bearbeiten",
            command=self.toggle_result_editing,
            style="Secondary.TButton",
            state="disabled",
        )
        self.edit_result_button.pack(side="left", padx=(8, 0))
        self.discard_edit_button = ttk.Button(
            self.result_line,
            text="Änderungen verwerfen",
            command=self.discard_manual_edits,
            style="Secondary.TButton",
            state="disabled",
        )
        self.discard_edit_button.pack(side="left", padx=(8, 0))
        self.copy_button = ttk.Button(
            self.result_line, text="Ergebnis kopieren", command=self.copy_result,
            style="Secondary.TButton", state="disabled"
        )
        self.copy_button.pack(side="right")
        self.output_text = scrolledtext.ScrolledText(outer, height=10, wrap="word", font=self.body_font, undo=True)
        self.output_text.configure(state="disabled")
        self.output_text.bind("<<Modified>>", self._output_changed)
        self.output_text.bind("<Escape>", lambda _event: self.discard_manual_edits())
        self.result_visible = False

        self.bottom = ttk.Frame(outer)
        self.bottom.pack(fill="x")
        self.result_status = ttk.Label(
            self.bottom,
            text=f"Text einfügen und auf „{primary_action_label(self.mistral_ready)}“ klicken.",
            style="Hint.TLabel",
        )
        self.help_button = ttk.Button(
            self.bottom,
            text="Info & Hilfe",
            command=self.open_help,
            style="Secondary.TButton",
        )
        self.protected_terms_button = ttk.Button(
            self.bottom,
            text="Begriffe schützen …",
            command=self.open_protected_terms,
            style="Secondary.TButton",
        )
        ttk.Button(self.bottom, text="Speichern", command=self.save_result, style="Secondary.TButton").pack(
            side="right"
        )
        ttk.Button(self.bottom, text="Leeren", command=self.clear_all, style="Secondary.TButton").pack(
            side="right", padx=(0, 8)
        )
        self.help_button.pack(side="left")
        self.protected_terms_button.pack(side="left", padx=(8, 0))
        self.result_status.pack(side="left", fill="x", expand=True, padx=(10, 8))
        ttk.Label(
            outer,
            text="Tastatur: Strg+Enter verbessern · Strg+E bearbeiten/prüfen · F1 Hilfe",
            style="Hint.TLabel",
        ).pack(anchor="e", pady=(8, 0))

        self._bind_shortcut("<F1>", self.open_help)
        self._bind_shortcut("<Control-o>", self.open_file)
        self._bind_shortcut("<Control-Shift-V>", self.paste_clipboard)
        self._bind_shortcut("<Control-Return>", self.start_processing)
        self._bind_shortcut("<Control-e>", self.toggle_result_editing)
        self._bind_shortcut("<Control-Shift-C>", self.copy_result)
        self._apply_text_palette(self.root)
        self.input_text.focus_set()

    def _apply_view_preferences(self) -> None:
        """Apply accessible fonts and colours immediately to all open windows."""
        large = self.ui_preferences.large_text
        sizes = (14, 14, 27, 21, 12, 12, 11) if large else (11, 11, 22, 17, 10, 10, 9)
        for font, size in zip(
            (self.body_font, self.body_bold_font, self.title_font, self.dialog_title_font,
             self.hint_font, self.hint_bold_font, self.mono_font),
            sizes,
            strict=True,
        ):
            font.configure(size=size)

        contrast = self.ui_preferences.high_contrast
        background = "#101010" if contrast else "#f4f7f5"
        foreground = "#ffffff" if contrast else "#17251e"
        hint = "#f2f2f2" if contrast else "#456054"
        field_background = "#000000" if contrast else "#ffffff"
        selected = "#ffd800" if contrast else "#0b6b3a"
        selected_text = "#000000" if contrast else "#ffffff"

        theme = "clam" if contrast and "clam" in self.style.theme_names() else self.default_theme
        self.style.theme_use(theme)
        self.root.configure(background=background)
        self.style.configure("TFrame", background=background)
        self.style.configure("TLabel", background=background, foreground=foreground, font=self.body_font)
        self.style.configure("TLabelframe", background=background, foreground=foreground)
        self.style.configure("TLabelframe.Label", background=background, foreground=foreground, font=self.body_bold_font)
        self.style.configure("TCheckbutton", background=background, foreground=foreground, font=self.body_font)
        self.style.configure("Title.TLabel", font=self.title_font, background=background, foreground=foreground)
        self.style.configure("Hint.TLabel", font=self.hint_font, background=background, foreground=hint)
        self.style.configure("Status.TLabel", font=self.hint_bold_font, padding=9)
        self.style.configure("Primary.TButton", font=self.body_bold_font, padding=(18, 10))
        self.style.configure("Secondary.TButton", font=self.hint_font, padding=(12, 8))
        self.style.configure("Accessible.TCombobox", font=self.body_font)
        if contrast:
            for style_name in ("TButton", "Primary.TButton", "Secondary.TButton"):
                self.style.configure(style_name, background="#ffffff", foreground="#000000")
                self.style.map(style_name, background=[("active", "#ffd800")])
            self.style.configure("TCombobox", fieldbackground=field_background, foreground=foreground)
        self._text_palette = {
            "background": field_background,
            "foreground": foreground,
            "insertbackground": foreground,
            "selectbackground": selected,
            "selectforeground": selected_text,
        }
        self._panel_background = background
        if hasattr(self, "root"):
            self._apply_text_palette(self.root)

    def _apply_text_palette(self, widget: object) -> None:
        """Apply the active palette to Tk text fields in a widget tree."""
        if isinstance(widget, self.tk.Text):
            try:
                widget.configure(**self._text_palette)
                if "changed" in widget.tag_names():
                    existing = str(widget.tag_cget("changed", "foreground")).lower()
                    is_after = existing in {"#145c2c", "#176b36", "#8cffad"}
                    widget.tag_configure(
                        "changed",
                        background=(
                            "#124522" if is_after else "#5c1111"
                        ) if self.ui_preferences.high_contrast else (
                            "#d9f5df" if is_after else "#ffd9d9"
                        ),
                        foreground=self._semantic_color("after" if is_after else "before"),
                    )
            except self.tk.TclError:
                pass
        elif isinstance(widget, self.tk.Canvas):
            try:
                widget.configure(background=self._panel_background)
            except self.tk.TclError:
                pass
        try:
            children = widget.winfo_children()
        except (AttributeError, self.tk.TclError):
            return
        for child in children:
            self._apply_text_palette(child)

    def _semantic_color(self, kind: str) -> str:
        """Return readable review colours for the current contrast mode."""
        if self.ui_preferences.high_contrast:
            return {"warning": "#ffd800", "before": "#ffb3b3", "after": "#8cffad"}[kind]
        return {"warning": "#8a4b08", "before": "#7a1111", "after": "#176b36"}[kind]

    def _save_view_preferences(self, large_text: bool, high_contrast: bool, status: object) -> None:
        """Persist and immediately apply accessibility settings."""
        self.ui_preferences = UiPreferences(large_text=large_text, high_contrast=high_contrast)
        self._apply_view_preferences()
        try:
            save_ui_preferences(self.ui_preferences)
        except OSError:
            status.configure(text="Ansicht aktiv; Speichern war nicht möglich.")
        else:
            status.configure(text="Ansicht gespeichert ✓")

    def _bind_shortcut(self, sequence: str, action: object) -> None:
        def invoke(_event: object) -> str:
            action()  # type: ignore[operator]
            return "break"

        self.root.bind(sequence, invoke)

    def _update_protected_terms_button(self) -> None:
        count = len(self.protected_terms)
        label = f"Geschützte Begriffe ({count}) …" if count else "Begriffe schützen …"
        self.protected_terms_button.configure(text=label)

    def open_protected_terms(self) -> None:
        """Open a focused optional dialog for exact terminology protection."""
        source = self.input_text.get("1.0", "end-1c")
        if not source.strip():
            self.messagebox.showinfo("Text fehlt", "Bitte zuerst den zu bearbeitenden Text einfügen.")
            self.input_text.focus_set()
            return
        window = self.tk.Toplevel(self.root)
        window.title("Begriffe schützen")
        window.geometry("620x430")
        window.minsize(520, 360)
        window.transient(self.root)
        outer = self.ttk.Frame(window, padding=20)
        outer.pack(fill="both", expand=True)
        self.ttk.Label(outer, text="Welche Begriffe dürfen sich nicht ändern?", font=self.dialog_title_font).pack(
            anchor="w"
        )
        self.ttk.Label(
            outer,
            text=(
                "Optional: einen Fachbegriff oder eine feste Bezeichnung pro Zeile eintragen. "
                "Groß-/Kleinschreibung und Anzahl bleiben exakt erhalten."
            ),
            wraplength=570,
        ).pack(anchor="w", pady=(4, 10))
        editor = self.scrolledtext.ScrolledText(outer, height=10, wrap="word", font=self.body_font, undo=True)
        editor.insert("1.0", "\n".join(self.protected_terms))
        editor.pack(fill="both", expand=True)
        self.ttk.Label(
            outer,
            text="Beispiele: UniCredit BulBank · Kontenabstimmung · Project Aurora",
            style="Hint.TLabel",
        ).pack(anchor="w", pady=(6, 10))

        def apply_terms() -> None:
            try:
                terms = normalize_protected_terms(editor.get("1.0", "end-1c").splitlines())
            except ValueError as error:
                self.messagebox.showerror("Begriffe prüfen", str(error), parent=window)
                return
            missing = missing_protected_terms(source, terms)
            if missing:
                preview = "\n".join(f"• {term}" for term in missing[:5])
                self.messagebox.showerror(
                    "Nicht im Text gefunden",
                    "Diese Begriffe kommen im Ausgangstext nicht exakt vor:\n\n" + preview,
                    parent=window,
                )
                return
            self.protected_terms = tuple(terms)
            self._update_protected_terms_button()
            self.result_status.configure(
                text=(f"{len(terms)} Begriff(e) werden exakt geschützt."
                      if terms else "Kein zusätzlicher Begriffsschutz aktiv.")
            )
            window.destroy()

        actions = self.ttk.Frame(outer)
        actions.pack(fill="x")
        self.ttk.Button(actions, text="Abbrechen", command=window.destroy).pack(side="right")
        self.ttk.Button(
            actions, text="Schutz übernehmen", command=apply_terms, style="Primary.TButton"
        ).pack(side="right", padx=(0, 8))
        self._apply_text_palette(window)
        editor.focus_set()

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
            self.changes_button.configure(state="disabled")
            self.edit_result_button.configure(state="disabled")
            self.discard_edit_button.configure(state="disabled")
            self.manual_result_verified = False
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
        missing_terms = missing_protected_terms(source, self.protected_terms)
        if missing_terms:
            self.messagebox.showerror(
                "Geschützten Begriff prüfen",
                "Mindestens ein geschützter Begriff kommt im aktuellen Text nicht mehr exakt vor:\n\n"
                + "\n".join(f"• {term}" for term in missing_terms[:5])
                + "\n\nBitte den Begriffsschutz anpassen.",
            )
            self.open_protected_terms()
            return
        self.run_button.configure(state="disabled", text=primary_action_label(self.mistral_ready))
        self.busy = True
        self.manual_result_verified = False
        self.copy_button.configure(state="disabled")
        self.input_text.configure(state="disabled")
        self.mode_box.configure(state="disabled")
        self.protected_terms_button.configure(state="disabled")
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
            args=(source, provider, strength, request_id, self.protected_terms),
            daemon=True,
        )
        thread.start()

    def use_safe_result_now(self, *, automatically: bool = False) -> None:
        """Abandon a slow model result and immediately produce the local fast version."""
        if not self.busy or not self.processing_active:
            return
        source = self.input_text.get("1.0", "end-1c")
        self.active_request_id += 1
        request_id = self.active_request_id
        self.processing_active = False
        self.run_button.configure(state="disabled", text=primary_action_label(self.mistral_ready))
        self.result_status.configure(
            text=("Zeitgrenze erreicht – sichere lokale Fassung wird erstellt …"
                  if automatically else "Sichere lokale Fassung wird sofort erstellt …")
        )
        thread = threading.Thread(
            target=self._worker,
            args=(
                source,
                "fast-editor",
                "medium",
                request_id,
                self.protected_terms,
                "provider_timeout" if automatically else "user_selected_safe_fallback",
            ),
            daemon=True,
            name="safe-editor-fallback",
        )
        thread.start()

    def _update_elapsed_time(self) -> None:
        if not self.processing_active:
            return
        elapsed_seconds = time.monotonic() - self.processing_started
        if elapsed_seconds >= MODEL_UI_DEADLINE_SECONDS:
            self.use_safe_result_now(automatically=True)
            return
        elapsed = int(elapsed_seconds)
        self.result_status.configure(
            text=f"Lokale Überarbeitung läuft … {elapsed} s (höchstens 45 s)"
        )
        self.root.after(1000, self._update_elapsed_time)

    def _worker(
        self,
        source: str,
        provider: str,
        strength: str,
        request_id: int,
        protected_terms: tuple[str, ...] = (),
        fallback_kind: str | None = None,
    ) -> None:
        try:
            options = TransformOptions(
                provider=provider,
                rewrite_strength=strength,
                language="auto-detect",
                preserve_citations=True,
                preserve_numbers=True,
                preserve_quotations=True,
                protected_terms=list(protected_terms),
            )
            result = run_pipeline(source, options)
            if fallback_kind is not None:
                result.audit.requested_provider = "rules+mistral-local"
                result.audit.options["provider"] = "rules+mistral-local"
                if fallback_kind == "provider_timeout":
                    result.audit.fact_preservation_warnings.append(ValidationWarning(
                        kind="provider_timeout",
                        severity="medium",
                        value="desktop_ui_deadline",
                        message=("Die Desktop-Zeitgrenze wurde erreicht; ausgegeben wurde die "
                                 "sichere lokale Schnellfassung."),
                    ))
                else:
                    result.audit.fact_preservation_warnings.append(ValidationWarning(
                        kind="user_selected_safe_fallback",
                        severity="medium",
                        value="safe_result_now",
                        message="Die sichere lokale Schnellfassung wurde manuell gewählt.",
                    ))
        except Exception as error:  # UI boundary: always return control to the user.
            self._schedule_ui(self._show_error, error, request_id)
            return
        self._schedule_ui(self._show_result, result, provider, request_id)

    def _schedule_ui(self, callback: object, *args: object) -> None:
        """Deliver worker results only while the Tk window still exists."""
        if self.closed:
            return
        self.ui_events.put((callback, args))

    def _drain_ui_events(self) -> None:
        """Run queued worker completions exclusively on Tk's main thread."""
        if self.closed:
            return
        while True:
            try:
                callback, args = self.ui_events.get_nowait()
            except queue.Empty:
                break
            callback(*args)  # type: ignore[operator]
        self.root.after(50, self._drain_ui_events)

    def _show_result(self, result: object, provider: str, request_id: int) -> None:
        if not request_is_current(request_id, self.active_request_id, self.closed):
            return
        self.busy = False
        self.processing_active = False
        self.progress.stop()
        self.run_button.configure(state="normal", text=primary_action_label(self.mistral_ready))
        self.input_text.configure(state="normal")
        self.mode_box.configure(state="readonly")
        self.protected_terms_button.configure(state="normal")
        rewritten = result.rewritten_text
        source = self.input_text.get("1.0", "end-1c")
        changed = rewritten != source
        if not self.result_visible:
            self.result_line.pack(fill="x", before=self.bottom)
            self.output_text.pack(fill="both", expand=True, pady=(6, 8), before=self.bottom)
            self.result_visible = True
        self._replace_output(rewritten)
        self.processed_source = source
        self.generated_result = rewritten
        self.last_audit = result.audit
        self.manual_result_verified = True
        self.verified_result_before_edit = rewritten
        self.copy_button.configure(state="normal")
        self.changes_button.configure(state="normal" if changed else "disabled")
        self.edit_result_button.configure(
            state="normal" if len(rewritten) <= CHANGE_PREVIEW_MAX_CHARACTERS else "disabled",
            text="Ergebnis bearbeiten",
        )
        self.discard_edit_button.configure(state="disabled")
        self.copy_button.focus_set()
        warning_kinds = {warning.kind for warning in result.audit.fact_preservation_warnings}
        if "model_input_too_long" in warning_kinds:
            message = "Text war für Mistral zu lang; vollständig lokal schnell bearbeitet."
        elif "provider_timeout" in warning_kinds:
            message = "Mistral hat die Zeitgrenze erreicht; sichere lokale Fassung angezeigt."
        elif "provider_unavailable" in warning_kinds:
            message = "Mistral war nicht rechtzeitig verfügbar; sicher bereinigtes Ergebnis angezeigt."
        elif "user_selected_safe_fallback" in warning_kinds:
            message = "Sichere lokale Fassung gewählt – bereit zum Kopieren."
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

    def _replace_output(self, text: str, *, editable: bool = False) -> None:
        self.output_text.configure(state="normal")
        self.output_text.delete("1.0", "end")
        self.output_text.insert("1.0", text)
        self.output_text.edit_modified(False)
        self.output_text.configure(state="normal" if editable else "disabled")
        self.output_editing = editable

    def _output_changed(self, _event: object | None = None) -> None:
        if not self.output_text.edit_modified():
            return
        self.output_text.edit_modified(False)
        if not self.output_editing:
            return
        self.manual_result_verified = False
        self.copy_button.configure(state="disabled")
        self.changes_button.configure(state="disabled")
        self.result_status.configure(
            text="Manuell geändert – vor dem Kopieren bitte die Fassung prüfen."
        )

    def _candidate_warnings(self, source: str, candidate: str) -> list[ValidationWarning]:
        if self.last_audit is None:
            return []
        options = self.last_audit.options
        return validate_preservation(
            source,
            candidate,
            self.last_audit.semantic_constraints,
            preserve_numbers=bool(options.get("preserve_numbers", True)),
            preserve_citations=bool(options.get("preserve_citations", True)),
            preserve_quotations=bool(options.get("preserve_quotations", True)),
        )

    def toggle_result_editing(self) -> None:
        source = self.input_text.get("1.0", "end-1c")
        if source != self.processed_source or self.busy:
            return
        if not self.output_editing:
            current = self.output_text.get("1.0", "end-1c")
            self.verified_result_before_edit = current
            self._replace_output(current, editable=True)
            self.manual_result_verified = False
            self.copy_button.configure(state="disabled")
            self.changes_button.configure(state="disabled")
            self.edit_result_button.configure(text="Manuelle Fassung prüfen")
            self.discard_edit_button.configure(state="normal")
            self.result_status.configure(
                text="Bearbeitungsmodus – Kopieren ist bis zum lokalen Schutzcheck gesperrt."
            )
            self.output_text.focus_set()
            return

        candidate = self.output_text.get("1.0", "end-1c")
        warnings = self._candidate_warnings(source, candidate)
        if warnings:
            summary = build_review_summary(self.last_audit.semantic_constraints, warnings)
            details = "\n".join(f"• {notice}" for notice in summary.notices[:5])
            self.messagebox.showwarning(
                "Manuelle Fassung noch nicht freigegeben",
                f"{summary.message}\n\n{details}\n\nBitte korrigiere die Fassung oder verwerfe die manuellen Änderungen.",
            )
            return
        self._replace_output(candidate)
        self.manual_result_verified = True
        self.copy_button.configure(state="normal")
        self.changes_button.configure(state="normal" if self.generated_result != source else "disabled")
        self.edit_result_button.configure(text="Ergebnis bearbeiten")
        self.discard_edit_button.configure(state="disabled")
        self.verified_result_before_edit = candidate
        self.result_status.configure(
            text="Manuelle Fassung geprüft – keine Abweichung bei den überwachten Inhalten gefunden; "
                 "keine Bedeutungs-Garantie."
        )
        self.copy_button.focus_set()

    def discard_manual_edits(self) -> None:
        """Restore the exact last verified result without running another transformation."""
        if not self.output_editing:
            return
        self._replace_output(self.verified_result_before_edit)
        self.manual_result_verified = True
        self.copy_button.configure(state="normal")
        source = self.input_text.get("1.0", "end-1c")
        self.changes_button.configure(state="normal" if self.generated_result != source else "disabled")
        self.edit_result_button.configure(state="normal", text="Ergebnis bearbeiten")
        self.discard_edit_button.configure(state="disabled")
        self.result_status.configure(text="Manuelle Änderungen verworfen – letzte geprüfte Fassung wiederhergestellt.")
        self.copy_button.focus_set()

    def _show_error(self, error: Exception, request_id: int) -> None:
        if not request_is_current(request_id, self.active_request_id, self.closed):
            return
        self.busy = False
        self.processing_active = False
        self.progress.stop()
        self.run_button.configure(state="normal", text=primary_action_label(self.mistral_ready))
        self.input_text.configure(state="normal")
        self.mode_box.configure(state="readonly")
        self.protected_terms_button.configure(state="normal")
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

    def support_text(self) -> str:
        """Return metadata-only diagnostics suitable for deliberate clipboard sharing."""
        return build_support_info(
            mistral_available=self.mistral_ready,
            diagnostic_log_available=diagnostic_log_path().exists(),
        ).as_text()

    def open_help(self) -> None:
        window = self.tk.Toplevel(self.root)
        window.title("Info & Hilfe")
        window.geometry("620x500")
        window.minsize(540, 440)
        window.transient(self.root)
        outer = self.ttk.Frame(window, padding=22)
        outer.pack(fill="both", expand=True)
        self.ttk.Label(
            outer,
            text=f"TextVerbessern {__version__}",
            font=self.dialog_title_font,
        ).pack(anchor="w")
        self.ttk.Label(
            outer,
            text="Lokale, sichere Textüberarbeitung ohne Cloud-Fallback.",
            wraplength=560,
        ).pack(anchor="w", pady=(4, 14))
        model_text = (
            "✓ Lokales Mistral ist verfügbar."
            if self.mistral_ready
            else "Schnelle lokale Bearbeitung ist verfügbar; Mistral ist optional."
        )
        self.ttk.Label(outer, text=model_text, font=self.hint_bold_font).pack(anchor="w")
        self.ttk.Label(
            outer,
            text=(
                "Bei Problemen kannst du die Diagnoseinformationen kopieren und an den Support senden. "
                "Sie enthalten keinen eingegebenen Text, keine Dokumentinhalte und keine Fehlermeldung."
            ),
            wraplength=560,
        ).pack(anchor="w", pady=(14, 8))
        shortcut_text = " · ".join(f"{key}: {label}" for key, label in KEYBOARD_SHORTCUTS.items())
        self.ttk.Label(
            outer,
            text=f"Tastatur: {shortcut_text}",
            wraplength=560,
        ).pack(anchor="w", pady=(0, 8))
        view = self.ttk.LabelFrame(outer, text="Ansicht", padding=(12, 8))
        view.pack(fill="x", pady=(0, 10))
        large_text = self.tk.BooleanVar(value=self.ui_preferences.large_text)
        high_contrast = self.tk.BooleanVar(value=self.ui_preferences.high_contrast)
        self.ttk.Checkbutton(view, text="Größere Schrift", variable=large_text).pack(side="left")
        self.ttk.Checkbutton(view, text="Hoher Kontrast", variable=high_contrast).pack(side="left", padx=(18, 0))
        view_status = self.ttk.Label(view, text="", style="Hint.TLabel")
        view_status.pack(side="right", padx=(8, 0))
        self.ttk.Button(
            view,
            text="Übernehmen",
            command=lambda: self._save_view_preferences(
                bool(large_text.get()), bool(high_contrast.get()), view_status
            ),
            style="Secondary.TButton",
        ).pack(side="right")
        report = self.tk.Text(outer, height=8, wrap="word", font=self.mono_font, relief="solid", borderwidth=1)
        report.insert("1.0", self.support_text())
        report.configure(state="disabled")
        report.pack(fill="both", expand=True, pady=(0, 12))
        actions = self.ttk.Frame(outer)
        actions.pack(fill="x")
        self.ttk.Button(actions, text="Schließen", command=window.destroy).pack(side="right")
        copy_button = self.ttk.Button(
            actions,
            text="Diagnoseinformationen kopieren",
            command=lambda: self._copy_support_info(copy_button),
            style="Primary.TButton",
        )
        copy_button.pack(side="right", padx=(0, 8))
        self._apply_text_palette(window)
        window.focus_set()

    def _copy_support_info(self, button: object) -> None:
        self.root.clipboard_clear()
        self.root.clipboard_append(self.support_text())
        self.root.update_idletasks()
        button.configure(text="Kopiert ✓")

    def open_change_preview(self) -> None:
        """Show a plain-language, side-by-side review without cluttering the main workflow."""
        source = self.input_text.get("1.0", "end-1c")
        displayed = self.output_text.get("1.0", "end-1c")
        if not result_is_current(source, self.processed_source, displayed, self.busy):
            self.messagebox.showinfo(
                "Kein aktuelles Ergebnis",
                "Bitte den aktuellen Ausgangstext zuerst erneut bearbeiten.",
            )
            return
        rewritten = self.generated_result
        if self.last_audit is None:
            self.messagebox.showinfo("Prüfung nicht verfügbar", "Bitte den Text erneut bearbeiten.")
            return
        if max(len(source), len(rewritten)) > CHANGE_PREVIEW_MAX_CHARACTERS:
            self.messagebox.showinfo(
                "Text sehr lang",
                "Die farbliche Ansicht ist für Texte bis 200.000 Zeichen verfügbar. "
                "Der vollständige fertige Text kann weiterhin kopiert oder gespeichert werden.",
            )
            return

        preview = build_change_preview(source, rewritten)
        window = self.tk.Toplevel(self.root)
        window.title("Änderungen prüfen")
        window.geometry("1080x700")
        window.minsize(760, 480)
        window.transient(self.root)

        outer = self.ttk.Frame(window, padding=18)
        outer.pack(fill="both", expand=True)
        summary = build_review_summary(
            self.last_audit.semantic_constraints,
            self.last_audit.fact_preservation_warnings,
        )
        summary_frame = self.ttk.LabelFrame(outer, text="Inhaltsprüfung", padding=10)
        summary_frame.pack(fill="x", pady=(0, 12))
        self.ttk.Label(
            summary_frame,
            text=summary.title,
            font=self.body_bold_font,
            foreground=self._semantic_color("warning" if summary.level == "review" else "after"),
        ).pack(anchor="w")
        self.ttk.Label(summary_frame, text=summary.message, wraplength=980).pack(anchor="w", pady=(3, 0))
        self.ttk.Label(summary_frame, text=summary.checked_values, style="Hint.TLabel").pack(
            anchor="w", pady=(5, 0)
        )
        for notice in summary.notices:
            self.ttk.Label(summary_frame, text=f"• {notice}", wraplength=980).pack(anchor="w", pady=(2, 0))
        self.ttk.Label(
            outer,
            text=f"{preview.change_groups} Änderungsbereich(e) · Rot = vorher · Grün = nachher",
            font=self.body_bold_font,
        ).pack(anchor="w", pady=(0, 10))
        columns = self.ttk.Frame(outer)
        columns.pack(fill="both", expand=True)
        columns.columnconfigure(0, weight=1)
        columns.columnconfigure(1, weight=1)
        columns.rowconfigure(1, weight=1)
        self.ttk.Label(columns, text="Original", font=self.hint_bold_font).grid(
            row=0, column=0, sticky="w", padx=(0, 6)
        )
        self.ttk.Label(columns, text="Verbesserung", font=self.hint_bold_font).grid(
            row=0, column=1, sticky="w", padx=(6, 0)
        )
        original_box = self.scrolledtext.ScrolledText(columns, wrap="word", font=self.hint_font)
        rewritten_box = self.scrolledtext.ScrolledText(columns, wrap="word", font=self.hint_font)
        original_box.grid(row=1, column=0, sticky="nsew", padx=(0, 6), pady=(5, 10))
        rewritten_box.grid(row=1, column=1, sticky="nsew", padx=(6, 0), pady=(5, 10))
        original_box.insert("1.0", source)
        rewritten_box.insert("1.0", rewritten)
        original_box.tag_configure(
            "changed",
            background="#5c1111" if self.ui_preferences.high_contrast else "#ffd9d9",
            foreground=self._semantic_color("before"),
        )
        rewritten_box.tag_configure(
            "changed",
            background="#124522" if self.ui_preferences.high_contrast else "#d9f5df",
            foreground=self._semantic_color("after"),
        )
        for start, end in preview.original_ranges:
            original_box.tag_add("changed", f"1.0 + {start} chars", f"1.0 + {end} chars")
        for start, end in preview.rewritten_ranges:
            rewritten_box.tag_add("changed", f"1.0 + {start} chars", f"1.0 + {end} chars")
        original_box.configure(state="disabled")
        rewritten_box.configure(state="disabled")

        actions = self.ttk.Frame(outer)
        actions.pack(fill="x")
        self.ttk.Button(actions, text="Schließen", command=window.destroy).pack(side="right")
        self.ttk.Button(
            actions,
            text="Verbesserung verwenden",
            command=lambda: self._use_reviewed_text(rewritten, window, improved=True),
            style="Primary.TButton",
        ).pack(side="right", padx=(0, 8))
        self.ttk.Button(
            actions,
            text="Original verwenden",
            command=lambda: self._use_reviewed_text(source, window, improved=False),
        ).pack(side="right", padx=(0, 8))
        if 1 < preview.change_groups <= INDIVIDUAL_CHANGE_MAX_GROUPS:
            self.ttk.Button(
                actions,
                text="Änderungen einzeln auswählen",
                command=lambda: (window.destroy(), self.open_individual_changes(source, rewritten)),
            ).pack(side="left")
        self._apply_text_palette(window)
        window.focus_set()

    @staticmethod
    def _change_excerpt(text: str, *, empty: str) -> str:
        compact = " ".join(text.split())
        if not compact:
            return empty
        return compact if len(compact) <= 100 else compact[:97] + "…"

    def open_individual_changes(self, source: str, rewritten: str) -> None:
        """Allow per-change decisions while preserving a mandatory semantic recheck."""
        segments = build_change_segments(source, rewritten)
        if not segments or len(segments) > INDIVIDUAL_CHANGE_MAX_GROUPS:
            return
        window = self.tk.Toplevel(self.root)
        window.title("Änderungen einzeln auswählen")
        window.geometry("820x650")
        window.minsize(650, 450)
        window.transient(self.root)
        outer = self.ttk.Frame(window, padding=18)
        outer.pack(fill="both", expand=True)
        self.ttk.Label(
            outer,
            text="Welche Verbesserungen möchtest du übernehmen?",
            font=self.dialog_title_font,
        ).pack(anchor="w")
        self.ttk.Label(
            outer,
            text=(
                "Alle Änderungen sind vorausgewählt. Deine Kombination wird vor der Übernahme "
                "erneut auf geschützte Inhalte und Struktur geprüft."
            ),
            wraplength=760,
        ).pack(anchor="w", pady=(3, 10))

        list_container = self.ttk.Frame(outer)
        list_container.pack(fill="both", expand=True, pady=(0, 12))
        canvas = self.tk.Canvas(list_container, highlightthickness=0)
        scrollbar = self.ttk.Scrollbar(list_container, orient="vertical", command=canvas.yview)
        list_frame = self.ttk.Frame(canvas)
        list_window = canvas.create_window((0, 0), window=list_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        list_frame.bind("<Configure>", lambda _event: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda event: canvas.itemconfigure(list_window, width=event.width))
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        selections = []
        for index, segment in enumerate(segments, start=1):
            selected = self.tk.BooleanVar(value=True)
            selections.append(selected)
            item = self.ttk.Frame(list_frame, padding=(8, 7))
            item.pack(fill="x")
            self.ttk.Checkbutton(
                item,
                text=f"Änderung {index} übernehmen",
                variable=selected,
            ).pack(anchor="w")
            before = self._change_excerpt(segment.before, empty="[wird eingefügt]")
            after = self._change_excerpt(segment.after, empty="[wird entfernt]")
            self.ttk.Label(
                item, text=f"Vorher: {before}", wraplength=720, foreground=self._semantic_color("before")
            ).pack(
                anchor="w", padx=(24, 0)
            )
            self.ttk.Label(
                item, text=f"Nachher: {after}", wraplength=720, foreground=self._semantic_color("after")
            ).pack(
                anchor="w", padx=(24, 0)
            )

        actions = self.ttk.Frame(outer)
        actions.pack(fill="x")
        self.ttk.Button(actions, text="Abbrechen", command=window.destroy).pack(side="right")
        self.ttk.Button(
            actions,
            text="Auswahl sicher übernehmen",
            command=lambda: self._apply_individual_changes(
                source,
                segments,
                tuple(bool(value.get()) for value in selections),
                window,
            ),
            style="Primary.TButton",
        ).pack(side="right", padx=(0, 8))
        self._apply_text_palette(window)
        window.focus_set()

    def _apply_individual_changes(
        self,
        source: str,
        segments: tuple[ChangeSegment, ...],
        selected: tuple[bool, ...],
        window: object,
    ) -> None:
        if self.last_audit is None:
            return
        candidate = apply_change_selection(source, segments, selected)
        warnings = self._candidate_warnings(source, candidate)
        if warnings:
            summary = build_review_summary(self.last_audit.semantic_constraints, warnings)
            details = "\n".join(f"• {notice}" for notice in summary.notices[:5])
            self.messagebox.showwarning(
                "Auswahl nicht übernommen",
                f"{summary.message}\n\n{details}\n\nBitte ändere die Auswahl oder verwende Original/Verbesserung vollständig.",
                parent=window,
            )
            return
        self._replace_output(candidate)
        self.manual_result_verified = True
        self.verified_result_before_edit = candidate
        self.copy_button.configure(state="normal")
        self.edit_result_button.configure(state="normal", text="Ergebnis bearbeiten")
        self.discard_edit_button.configure(state="disabled")
        self.result_status.configure(text="Geprüfte Einzelauswahl übernommen – bereit zum Kopieren.")
        self.copy_button.focus_set()
        window.destroy()

    def _use_reviewed_text(self, text: str, window: object, *, improved: bool) -> None:
        self._replace_output(text)
        self.manual_result_verified = True
        self.verified_result_before_edit = text
        self.copy_button.configure(state="normal")
        self.edit_result_button.configure(state="normal", text="Ergebnis bearbeiten")
        self.discard_edit_button.configure(state="disabled")
        self.changes_button.configure(state="normal" if self.generated_result != self.processed_source else "disabled")
        self.result_status.configure(
            text="Verbesserung ausgewählt – bereit zum Kopieren."
            if improved
            else "Original ausgewählt – bereit zum Kopieren."
        )
        self.copy_button.focus_set()
        window.destroy()

    def copy_result(self) -> None:
        source = self.input_text.get("1.0", "end-1c")
        result = self.output_text.get("1.0", "end-1c")
        if not self.manual_result_verified or not result_is_current(
            source, self.processed_source, result, self.busy
        ):
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
        if not self.manual_result_verified or not result_is_current(
            source, self.processed_source, result, self.busy
        ):
            self.messagebox.showinfo(
                "Kein aktuelles Ergebnis",
                "Bitte den aktuellen Ausgangstext bearbeiten und manuelle Änderungen zuerst prüfen; "
                "eine ungeprüfte oder ältere Fassung wird nicht gespeichert.",
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
        self._replace_output("")
        self.copy_button.configure(state="disabled")
        self.copy_button.configure(text="Ergebnis kopieren")
        self.changes_button.configure(state="disabled")
        self.edit_result_button.configure(state="disabled", text="Ergebnis bearbeiten")
        self.discard_edit_button.configure(state="disabled")
        self.processed_source = None
        self.generated_result = ""
        self.last_audit = None
        self.manual_result_verified = False
        self.verified_result_before_edit = ""
        self.protected_terms = ()
        self._update_protected_terms_button()
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
