from app import __version__
from app.support import build_support_info


def test_support_report_is_useful_and_explicitly_content_free() -> None:
    report = build_support_info(
        mistral_available=True,
        diagnostic_log_available=False,
    ).as_text()

    assert f"TextVerbessern: {__version__}" in report
    assert "Lokales Mistral verfügbar: ja" in report
    assert "Diagnoseprotokoll vorhanden: nein" in report
    assert "kein Cloud-Fallback" in report
    assert "kein Eingabetext" in report


def test_support_report_contains_no_user_identity_path_or_document_content(monkeypatch) -> None:
    monkeypatch.setenv("USERNAME", "SENSITIVE-USER")
    monkeypatch.setenv("USERPROFILE", r"C:\Users\SENSITIVE-USER")
    secret_text = "INTERNAL AUDIT BALANCE EUR 1.234,56"

    report = build_support_info(
        mistral_available=False,
        diagnostic_log_available=True,
    ).as_text()

    assert "SENSITIVE-USER" not in report
    assert "C:\\Users" not in report
    assert secret_text not in report
    assert "Lokales Mistral verfügbar: nein" in report
    assert "Diagnoseprotokoll vorhanden: ja" in report
