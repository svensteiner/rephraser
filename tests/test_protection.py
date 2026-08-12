from __future__ import annotations

import pytest

from app.models import TransformOptions
from app.pipeline import run_pipeline
from app.protection import (
    missing_protected_terms,
    normalize_protected_terms,
    transform_outside_protected_terms,
)
from app.providers.base import EditorialProvider


def test_normalizes_deduplicates_and_limits_terms() -> None:
    assert normalize_protected_terms([" Project Aurora ", "Project Aurora", "Kontenabstimmung"]) == [
        "Project Aurora",
        "Kontenabstimmung",
    ]
    with pytest.raises(ValueError, match="höchstens 50"):
        normalize_protected_terms([f"Term {index}" for index in range(51)])
    with pytest.raises(ValueError, match="unsichtbaren"):
        normalize_protected_terms(["Project\u200bAurora"])


def test_reports_terms_that_are_not_exactly_in_source() -> None:
    assert missing_protected_terms("Project Aurora ist aktiv.", ["Project Aurora", "project aurora"]) == [
        "project aurora"
    ]


def test_transforms_only_outside_every_protected_occurrence() -> None:
    source = "Alpha intern, Alpha extern und Beta intern."
    transformed = transform_outside_protected_terms(source, ["Alpha"], lambda value: value.replace("intern", "INTERN"))
    assert transformed == "Alpha INTERN, Alpha extern und Beta INTERN."


def test_fast_editor_keeps_explicit_phrase_but_improves_other_prose() -> None:
    source = "We would like to better understand Project Aurora. In order to proceed, we need details."
    result = run_pipeline(
        source,
        TransformOptions(provider="fast-editor", protected_terms=["We would like to better understand"]),
    )
    assert result.rewritten_text == "We would like to better understand Project Aurora. To proceed, we need details."
    assert result.audit.semantic_constraints.protected_terms == ["We would like to better understand"]
    assert not result.audit.fact_preservation_warnings


def test_rule_cleanup_preserves_exact_term_including_non_breaking_space() -> None:
    source = "Project\u00a0Aurora und Wien\u00a0West"
    result = run_pipeline(source, TransformOptions(provider="rules", protected_terms=["Project\u00a0Aurora"]))
    assert result.rewritten_text == "Project\u00a0Aurora und Wien West"
    assert not result.audit.fact_preservation_warnings


class TermChangingProvider(EditorialProvider):
    name = "mistral-local"

    def rewrite(self, text, constraints, options):
        return text.replace("Project Aurora", "Project Borealis")


def test_changed_explicit_term_rejects_model_rewrite() -> None:
    source = "Project Aurora bleibt unverändert."
    result = run_pipeline(
        source,
        TransformOptions(protected_terms=["Project Aurora"]),
        provider=TermChangingProvider(),
    )
    assert result.rewritten_text == source
    assert any(warning.kind == "rewrite_rejected" for warning in result.audit.fact_preservation_warnings)


def test_absent_requested_term_is_a_visible_audit_warning() -> None:
    result = run_pipeline("Ein Text.", TransformOptions(provider="rules", protected_terms=["Project Aurora"]))
    warning = next(w for w in result.audit.fact_preservation_warnings if w.kind == "protected_term_not_found")
    assert warning.value == "Project Aurora"
