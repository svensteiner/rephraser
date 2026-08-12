"""Privacy-preserving support information for the native desktop app."""

from __future__ import annotations

from dataclasses import dataclass
import platform
import sys

from app import __version__


@dataclass(frozen=True, slots=True)
class SupportInfo:
    version: str
    runtime: str
    python_version: str
    operating_system: str
    architecture: str
    mistral_available: bool
    diagnostic_log_available: bool

    def as_text(self) -> str:
        return "\n".join(
            (
                f"TextVerbessern: {self.version}",
                f"Laufzeit: {self.runtime}",
                f"Python: {self.python_version}",
                f"Betriebssystem: {self.operating_system}",
                f"Architektur: {self.architecture}",
                f"Lokales Mistral verfügbar: {'ja' if self.mistral_available else 'nein'}",
                f"Diagnoseprotokoll vorhanden: {'ja' if self.diagnostic_log_available else 'nein'}",
                "Verarbeitung: lokal; kein Cloud-Fallback",
                "Datenschutz: kein Eingabetext in diesen Diagnoseinformationen",
            )
        )


def build_support_info(*, mistral_available: bool, diagnostic_log_available: bool) -> SupportInfo:
    frozen = bool(getattr(sys, "frozen", False))
    return SupportInfo(
        version=__version__,
        runtime="portable Windows-App" if frozen else "Python-Anwendung",
        python_version=platform.python_version(),
        operating_system=f"{platform.system()} {platform.release()}",
        architecture=platform.machine() or "unbekannt",
        mistral_available=mistral_available,
        diagnostic_log_available=diagnostic_log_available,
    )
