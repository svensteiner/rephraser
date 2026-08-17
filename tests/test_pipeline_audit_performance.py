import time

from app.models import TransformOptions
from app.pipeline import run_pipeline
from app.providers.base import EditorialProvider


class LargeRepeatedTextStub(EditorialProvider):
    """A deterministic rewrite that isolates audit generation in this regression test."""

    name = "audit-performance-stub"

    def rewrite(self, text, constraints, options):
        return text.replace("content", "revised", 1)


def test_large_repetitive_rewrite_uses_explicit_bounded_transformation_audit() -> None:
    source = ("content " * 8_000).strip()

    started = time.perf_counter()
    result = run_pipeline(
        source,
        TransformOptions(provider="rules"),
        provider=LargeRepeatedTextStub(),
    )
    elapsed = time.perf_counter() - started

    assert elapsed < 5.0
    assert result.rewritten_text.startswith("revised ")
    assert len(result.audit.transformations) == 1
    summary = result.audit.transformations[0]
    assert summary.kind == "bounded_summary"
    assert summary.before == summary.after == ""
    assert summary.original_start == summary.original_end == 0
    assert summary.rewritten_start == summary.rewritten_end == 0
    assert "not enumerated" in summary.reason

    warning = next(
        item
        for item in result.audit.fact_preservation_warnings
        if item.kind == "transformation_audit_truncated"
    )
    assert warning.severity == "low"
    assert "original_characters=" in warning.value
    assert "complete enumeration" in warning.message
