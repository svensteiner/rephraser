from app.models import SemanticConstraints, ValidationWarning
from app.review_summary import build_review_summary


def constraints() -> SemanticConstraints:
    return SemanticConstraints(
        core_claims=["Anna Müller bestätigte am 3. März 2026 einen Wert von 12,5 %."],
        facts=[],
        numbers=["12,5 %"],
        names=["Anna Müller"],
        dates=["3. März 2026"],
        quotations=["„Bestätigt.“"],
        citations=["https://example.org"],
        argument_structure=[],
        uncertainties=[],
        must_preserve=[],
    )


def warning(kind: str, value: str = "Wert") -> ValidationWarning:
    return ValidationWarning(kind=kind, severity="high", value=value, message="technical")


def test_review_summary_reports_exact_scope_without_claiming_proof() -> None:
    summary = build_review_summary(constraints(), [])

    assert summary.level == "passed"
    assert "Automatische Inhaltsprüfung bestanden" in summary.title
    assert "Bitte wichtige Texte dennoch selbst lesen" in summary.message
    assert summary.checked_values == (
        "Automatisch geprüft: 2 Zahlen/Daten · 1 Name · 1 Quelle/Link · 1 Zitat · 1 Aussage"
    )
    assert summary.notices == ()


def test_review_summary_reports_user_selected_protected_terms() -> None:
    selected = constraints().model_copy(update={"protected_terms": ["Project Aurora"]})
    summary = build_review_summary(selected, [])
    assert summary.checked_values.endswith(" · 1 eigener Begriff")


def test_review_summary_explains_automatic_rejection_as_safe_fallback() -> None:
    summary = build_review_summary(
        constraints(),
        [
            warning("rewrite_rejected", "altered_negation"),
            warning("provider_timeout", "provider_timeout"),
        ],
    )

    assert summary.level == "protected"
    assert "automatisch verworfen" in summary.title
    assert "sichere lokale Grundbereinigung" in summary.message
    assert any("Zeitgrenze" in notice for notice in summary.notices)
    assert any("inhaltlich veränderte Fassung" in notice for notice in summary.notices)


def test_review_summary_treats_user_selected_safe_fallback_as_information() -> None:
    summary = build_review_summary(
        constraints(),
        [warning("user_selected_safe_fallback", "safe_result_now")],
    )
    assert summary.level == "passed"
    assert any("auf Wunsch" in notice for notice in summary.notices)


def test_review_summary_never_hides_remaining_semantic_warning() -> None:
    summary = build_review_summary(
        constraints(),
        [warning("missing_number", "12,5 %")],
    )

    assert summary.level == "review"
    assert "Bitte inhaltlich prüfen" in summary.title
    assert summary.notices == ("Geschützter Wert fehlt möglicherweise: 12,5 %",)


def test_review_summary_translates_reassignment_and_new_claim_warnings() -> None:
    summary = build_review_summary(
        constraints(),
        [
            warning("reassigned_numeric_context", "EUR 10"),
            warning("unsupported_new_claim", "Neue Behauptung"),
        ],
    )

    assert summary.level == "review"
    assert any("anderen Aussage zugeordnet" in notice for notice in summary.notices)
    assert any("Neue Aussage" in notice for notice in summary.notices)
