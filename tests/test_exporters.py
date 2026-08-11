import json

from app.exporters import export_result
from app.models import TransformOptions
from app.pipeline import run_pipeline


def test_export_returns_and_writes_text_audit_and_diff_paths(tmp_path) -> None:
    result = run_pipeline("Grüße\u00a0aus Wien.", TransformOptions(provider="rules"))
    output = tmp_path / "result.md"
    paths = export_result(result, output)
    expected = (
        output,
        tmp_path / "result.md.audit.json",
        tmp_path / "result.md.diff.txt",
    )
    assert paths == expected
    assert output.read_text(encoding="utf-8") == "Grüße aus Wien."
    audit = json.loads(expected[1].read_text(encoding="utf-8"))
    assert audit["original_hash"] == result.audit.original_hash
    assert "inspection_after" in audit
    assert expected[2].read_text(encoding="utf-8").strip()


def test_export_honors_explicit_audit_and_diff_paths(tmp_path) -> None:
    result = run_pipeline("Ein klarer Satz.", TransformOptions(provider="rules"))
    paths = export_result(
        result,
        tmp_path / "result.txt",
        audit_path=tmp_path / "audit" / "report.json",
        diff_path=tmp_path / "diff" / "changes.txt",
    )
    assert paths[1].is_file()
    assert paths[2].is_file()
