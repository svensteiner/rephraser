"""Native Windows interface for the portable TextVerbessern application."""

from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import threading
import urllib.error
import urllib.request
from urllib.parse import urlparse

from app.models import TransformOptions
from app.pipeline import run_pipeline
from app.providers.base import ProviderError


MODE_AUTOMATIC = "Automatisch (empfohlen)"
MODE_SAFE = "Nur sichere Bereinigung"
MODE_STRONG = "Deutlich umformulieren"


def local_mistral_ready(timeout: float = 0.8) -> bool:
    """Check the configured loopback Ollama endpoint without sending user text."""
    base_url = os.getenv("MISTRAL_BASE_URL", "http://127.0.0.1:11434").rstrip("/")
    model = os.getenv("MISTRAL_MODEL", "mistral").split(":", 1)[0]
    parsed = urlparse(base_url)
    if (
        parsed.scheme != "http"
        or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        return False

    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
            return None

    try:
        opener = urllib.request.build_opener(NoRedirect)
        with opener.open(base_url + "/api/tags", timeout=timeout) as response:
            payload = json.load(response)
        return any(item.get("name", "").split(":", 1)[0] == model for item in payload.get("models", []))
    except (OSError, ValueError, KeyError, urllib.error.URLError):
        return False


def processing_settings(mode: str, mistral_ready: bool) -> tuple[str, str]:
    """Map user-facing choices to safe internal provider settings."""
    if mode == MODE_SAFE or not mistral_ready:
        return "rules", "light"
    if mode == MODE_STRONG:
        return "rules+mistral-local", "substantial"
    return "rules+mistral-local", "medium"


def run_self_test() -> dict[str, object]:
    """Run a dependency-free functional check suitable for packaged builds."""
    source = "Grüße\u00a0aus Wien – 12,5 % am 3. März 2026."
    result = run_pipeline(source, TransformOptions(provider="rules", rewrite_strength="light"))
    expected = "Grüße aus Wien – 12,5 % am 3. März 2026."
    protected = all(value in result.rewritten_text for value in ("Grüße", "12,5 %", "3. März 2026"))
    return {
        "ok": result.rewritten_text == expected and protected,
        "safe_cleanup": result.rewritten_text == expected,
        "protected_values": protected,
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
            "✓ Lokale sprachliche Überarbeitung ist verfügbar."
            if self.mistral_ready
            else "ℹ Sichere Grundbereinigung verfügbar; lokales Sprachmodell nicht gefunden."
        )
        self.system_status = ttk.Label(outer, text=status_text, style="Status.TLabel")
        self.system_status.pack(fill="x", pady=(0, 12))

        top_line = ttk.Frame(outer)
        top_line.pack(fill="x")
        ttk.Label(top_line, text="Dein Text", font=("Segoe UI", 11, "bold")).pack(side="left")
        ttk.Button(top_line, text="Datei öffnen", command=self.open_file, style="Secondary.TButton").pack(side="right")
        self.input_text = scrolledtext.ScrolledText(outer, height=10, wrap="word", font=("Segoe UI", 11), undo=True)
        self.input_text.pack(fill="both", expand=True, pady=(6, 10))

        controls = ttk.Frame(outer)
        controls.pack(fill="x", pady=(0, 10))
        ttk.Label(controls, text="Bearbeitung:").pack(side="left")
        self.mode = tk.StringVar(value=MODE_AUTOMATIC)
        self.mode_box = ttk.Combobox(
            controls,
            textvariable=self.mode,
            values=(MODE_AUTOMATIC, MODE_SAFE, MODE_STRONG),
            state="readonly",
            width=28,
        )
        self.mode_box.pack(side="left", padx=(8, 14))
        self.run_button = ttk.Button(
            controls, text="Text überarbeiten", command=self.start_processing, style="Primary.TButton"
        )
        self.run_button.pack(side="right")
        self.progress = ttk.Progressbar(controls, mode="indeterminate", length=150)
        self.progress.pack(side="right", padx=12)

        result_line = ttk.Frame(outer)
        result_line.pack(fill="x")
        ttk.Label(result_line, text="Fertiger Text", font=("Segoe UI", 11, "bold")).pack(side="left")
        self.copy_button = ttk.Button(
            result_line, text="Ergebnis kopieren", command=self.copy_result, style="Secondary.TButton", state="disabled"
        )
        self.copy_button.pack(side="right")
        self.output_text = scrolledtext.ScrolledText(outer, height=10, wrap="word", font=("Segoe UI", 11), undo=True)
        self.output_text.pack(fill="both", expand=True, pady=(6, 8))

        bottom = ttk.Frame(outer)
        bottom.pack(fill="x")
        self.result_status = ttk.Label(bottom, text="Text einfügen und auf „Text überarbeiten“ klicken.", style="Hint.TLabel")
        self.result_status.pack(side="left")
        ttk.Button(bottom, text="Leeren", command=self.clear_all, style="Secondary.TButton").pack(side="right")
        ttk.Button(bottom, text="Speichern", command=self.save_result, style="Secondary.TButton").pack(
            side="right", padx=(0, 8)
        )

        self.root.bind("<Control-Return>", lambda _event: self.start_processing())
        self.root.bind("<Control-Shift-C>", lambda _event: self.copy_result())
        self.input_text.focus_set()

    def open_file(self) -> None:
        path = self.filedialog.askopenfilename(filetypes=(("Text und Markdown", "*.txt *.md"), ("Alle Dateien", "*.*")))
        if not path:
            return
        try:
            content = Path(path).read_text(encoding="utf-8-sig")
        except (OSError, UnicodeError) as error:
            self.messagebox.showerror("Datei nicht lesbar", f"Die Datei konnte nicht geöffnet werden.\n\n{error}")
            return
        self.input_text.delete("1.0", "end")
        self.input_text.insert("1.0", content)

    def start_processing(self) -> None:
        source = self.input_text.get("1.0", "end-1c")
        if not source.strip():
            self.messagebox.showinfo("Text fehlt", "Bitte zuerst einen Text einfügen.")
            self.input_text.focus_set()
            return
        self.run_button.configure(state="disabled")
        self.copy_button.configure(state="disabled")
        self.progress.start(12)
        self.result_status.configure(text="Lokale Bearbeitung läuft …")
        provider, strength = processing_settings(self.mode.get(), self.mistral_ready)
        thread = threading.Thread(target=self._worker, args=(source, provider, strength), daemon=True)
        thread.start()

    def _worker(self, source: str, provider: str, strength: str) -> None:
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
            self.root.after(0, self._show_error, error)
            return
        self.root.after(0, self._show_result, result, provider)

    def _show_result(self, result: object, provider: str) -> None:
        self.progress.stop()
        self.run_button.configure(state="normal")
        rewritten = result.rewritten_text
        self.output_text.delete("1.0", "end")
        self.output_text.insert("1.0", rewritten)
        self.copy_button.configure(state="normal")
        rejected = any(warning.kind == "rewrite_rejected" for warning in result.audit.fact_preservation_warnings)
        if rejected:
            message = "Sicher bereinigt; eine unsichere Modellfassung wurde verworfen."
        elif result.audit.fact_preservation_warnings:
            message = f"Fertig – bitte {len(result.audit.fact_preservation_warnings)} Prüfhinweis(e) beachten."
        elif "mistral" in provider:
            message = "Fertig – lokal überarbeitet; geschützte Angaben ohne Auffälligkeit."
        else:
            message = "Fertig – lokal sicher bereinigt."
        self.result_status.configure(text=message)

    def _show_error(self, error: Exception) -> None:
        self.progress.stop()
        self.run_button.configure(state="normal")
        if isinstance(error, ProviderError):
            message = "Das lokale Sprachmodell antwortet nicht. Der Text wurde nicht versendet."
        else:
            message = "Die Bearbeitung konnte nicht abgeschlossen werden. Der eingegebene Text bleibt erhalten."
        self.result_status.configure(text=message)
        self.messagebox.showerror("Bearbeitung nicht möglich", f"{message}\n\nTechnische Information: {error}")

    def copy_result(self) -> None:
        result = self.output_text.get("1.0", "end-1c")
        if not result:
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(result)
        self.root.update_idletasks()
        self.result_status.configure(text="Kopiert ✓")

    def save_result(self) -> None:
        result = self.output_text.get("1.0", "end-1c")
        if not result:
            self.messagebox.showinfo("Kein Ergebnis", "Es gibt noch keinen fertigen Text zum Speichern.")
            return
        path = self.filedialog.asksaveasfilename(
            defaultextension=".txt", filetypes=(("Textdatei", "*.txt"), ("Markdown", "*.md"))
        )
        if not path:
            return
        try:
            Path(path).write_text(result, encoding="utf-8", newline="\n")
        except OSError as error:
            self.messagebox.showerror("Speichern fehlgeschlagen", str(error))
            return
        self.result_status.configure(text="Gespeichert ✓")

    def clear_all(self) -> None:
        self.input_text.delete("1.0", "end")
        self.output_text.delete("1.0", "end")
        self.copy_button.configure(state="disabled")
        self.result_status.configure(text="Text einfügen und auf „Text überarbeiten“ klicken.")
        self.input_text.focus_set()

    def run(self) -> None:
        self.root.mainloop()


def main(argv: list[str] | None = None) -> int:
    arguments = argv if argv is not None else sys.argv[1:]
    if "--self-test" in arguments:
        report = run_self_test()
        print(json.dumps(report, ensure_ascii=False))
        return 0 if report["ok"] else 1
    DesktopApp().run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
