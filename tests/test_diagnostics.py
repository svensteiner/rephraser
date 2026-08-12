import json

from app.diagnostics import diagnostic_log_path, write_diagnostic_event


def test_diagnostic_log_never_contains_exception_message_or_user_text(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    secret = "VERTRAULICHER MANDANTENTEXT"
    path = write_diagnostic_event("processing_failed", RuntimeError(secret))
    assert path == diagnostic_log_path()
    content = path.read_text(encoding="utf-8")
    assert secret not in content
    record = json.loads(content)
    assert record["event"] == "processing_failed"
    assert record["exception_type"] == "RuntimeError"
    assert record["version"] == "1.10.0"
