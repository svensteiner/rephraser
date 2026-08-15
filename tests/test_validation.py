import pytest

import app.validation as validation
from app.semantic import extract_semantics
from app.validation import validate_preservation


def test_warns_for_changed_number_date_name_quote_and_url() -> None:
    original = 'Anna Müller sagte am 12.03.2026: „Plus 5 %.“ https://example.org'
    warnings = validate_preservation(original, "Der Wert stieg.", extract_semantics(original))
    kinds = {warning.kind for warning in warnings}
    assert {"missing_number", "missing_date", "missing_proper_name", "missing_quotation", "missing_citation"} <= kinds


def test_detects_new_numeric_claim() -> None:
    warnings = validate_preservation("Der Wert stieg.", "Der Wert stieg um 20 %.", extract_semantics("Der Wert stieg."))
    assert any(w.kind == "new_number" for w in warnings)


def test_meaning_neutral_invisible_cleanup_does_not_invent_a_new_name() -> None:
    original = "A\u200bB und Soft\u00adhyphen"
    rewritten = "AB und Softhyphen"
    warnings = validate_preservation(original, rewritten, extract_semantics(original))
    assert not any(w.kind == "new_proper_name" for w in warnings)


def test_detects_added_claim_and_changed_url_embedding() -> None:
    original = "Die Marge betrug 12,5 %. Quelle: https://example.org/report."
    rewritten = ("Die Marge betrug 12,5 %. Quelle: <https://example.org/report>. "
                 "Der Betrag der Marge wurde in Euro angegeben.")
    warnings = validate_preservation(original, rewritten, extract_semantics(original))
    kinds = {warning.kind for warning in warnings}
    assert "altered_citation_format" in kinds
    assert "unsupported_new_claim" in kinds


def test_duplicate_protected_fact_is_rejected() -> None:
    original = "Die Marge beträgt 12,5 %."
    constraints = extract_semantics(original)
    warnings = validate_preservation(
        original,
        "Die Marge beträgt 12,5 %. Die Marge beträgt 12,5 %.",
        constraints,
    )
    assert any(w.kind == "altered_number_count" for w in warnings)


def test_duplicate_proper_name_is_rejected() -> None:
    original = "Anna Müller genehmigte den Bericht."
    rewritten = "Anna Müller genehmigte den Bericht für Anna Müller."
    warnings = validate_preservation(original, rewritten, extract_semantics(original))
    assert any(w.kind == "altered_proper_name_count" and w.value == "Anna Müller" for w in warnings)


def test_explicit_protected_term_must_remain_exact_and_keep_its_count() -> None:
    original = "Project Aurora gehört zu Project Aurora Holding."
    constraints = extract_semantics(original, ["Project Aurora"])
    missing = validate_preservation(original, "Project Borealis gehört zur Holding.", constraints)
    duplicated = validate_preservation(original, original + " Project Aurora.", constraints)
    assert any(w.kind == "missing_protected_term" for w in missing)
    assert any(w.kind == "altered_protected_term_count" for w in duplicated)


def test_new_name_and_quotation_are_reported_symmetrically() -> None:
    original = "Die Marge blieb stabil."
    rewritten = 'Die Marge blieb stabil. Anna Müller sagte: "Bestätigt."'
    warnings = validate_preservation(original, rewritten, extract_semantics(original))
    kinds = {warning.kind for warning in warnings}
    assert "new_proper_name" in kinds
    assert "new_quotation" in kinds


def test_detects_negation_uncertainty_and_claim_loss() -> None:
    original = ("Der Umsatz dürfte steigen. Der Gewinn wird nicht sinken. "
                "Die langfristigen Lieferverträge sichern stabile Beschaffungskosten.")
    rewritten = "Der Umsatz wird steigen. Der Gewinn wird sinken."
    warnings = validate_preservation(original, rewritten, extract_semantics(original))
    kinds = {warning.kind for warning in warnings}
    assert "altered_negation" in kinds
    assert "altered_uncertainty" in kinds
    assert "missing_or_reassigned_claim" in kinds


def test_detects_markdown_structure_and_code_changes() -> None:
    original = "# Titel\n\n- Punkt  \n\n```python\nx = 1\n```\n\n`code` [Quelle](https://example.org)"
    rewritten = "Titel\n\nPunkt\n\npython\nx = 2\n\ncode [Quelle](https://example.org)"
    warnings = validate_preservation(original, rewritten, extract_semantics(original))
    changed = [warning.value for warning in warnings if warning.kind == "altered_markdown_structure"]
    assert {"fenced_code", "inline_code", "headings", "lists", "hard_breaks"} <= set(changed)


def test_accepts_compact_claim_with_same_subject_and_intent() -> None:
    original = "We would like to better understand the account structure."
    rewritten = "Account structure details requested."
    warnings = validate_preservation(original, rewritten, extract_semantics(original))
    assert not any(w.kind == "missing_or_reassigned_claim" for w in warnings)


def test_detects_numbers_swapped_between_factual_contexts() -> None:
    original = "Revenue increased to EUR 10; operating profit declined to EUR 5."
    rewritten = "Revenue increased to EUR 5; operating profit declined to EUR 10."
    warnings = validate_preservation(original, rewritten, extract_semantics(original))
    reassigned = {warning.value for warning in warnings if warning.kind == "reassigned_numeric_context"}
    assert reassigned == {"EUR 10", "EUR 5"}


def test_allows_rewording_around_numbers_when_associations_stay_intact() -> None:
    original = "Revenue increased to EUR 10; operating profit declined to EUR 5."
    rewritten = "Revenue rose to EUR 10; operating profit fell to EUR 5."
    warnings = validate_preservation(original, rewritten, extract_semantics(original))
    assert not any(w.kind == "reassigned_numeric_context" for w in warnings)


def test_detects_names_swapped_between_claims() -> None:
    original = "Anna Müller approved the audit; Bernd Klein rejected the proposal."
    rewritten = "Bernd Klein approved the audit; Anna Müller rejected the proposal."
    warnings = validate_preservation(original, rewritten, extract_semantics(original))
    reassigned = {warning.value for warning in warnings if warning.kind == "reassigned_proper_name_context"}
    assert reassigned == {"Anna Müller", "Bernd Klein"}


def test_detects_numbers_swapped_between_markdown_list_items() -> None:
    original = "- Revenue increased to EUR 10\n- Operating profit declined to EUR 5"
    rewritten = "- Revenue increased to EUR 5\n- Operating profit declined to EUR 10"
    warnings = validate_preservation(original, rewritten, extract_semantics(original))
    assert any(w.kind == "reassigned_numeric_context" for w in warnings)


@pytest.mark.parametrize(
    ("original", "rewritten", "warning_kind", "marker"),
    [
        (
            "The contract permits the transfer only with prior written consent.",
            "The contract prohibits the transfer only with prior written consent.",
            "changed_claim_polarity",
            "permission: permits -> prohibits",
        ),
        (
            "The control is effective for the reporting period.",
            "The control is ineffective for the reporting period.",
            "changed_claim_polarity",
            "effectiveness: effective -> ineffective",
        ),
        (
            "Die Gesellschaft darf die Mittel nur mit Zustimmung verwenden.",
            "Die Gesellschaft muss die Mittel nur mit Zustimmung verwenden.",
            "changed_modal_obligation",
            "modal obligation: darf -> muss",
        ),
        (
            "Revenue may increase in the next quarter.",
            "Revenue may decrease in the next quarter.",
            "changed_claim_polarity",
            "direction: increase -> decrease",
        ),
    ],
)
def test_detects_high_risk_polarity_and_modal_inversions(
    original: str,
    rewritten: str,
    warning_kind: str,
    marker: str,
) -> None:
    warnings = validate_preservation(original, rewritten, extract_semantics(original))
    assert any(warning.kind == warning_kind and warning.value == marker for warning in warnings)


def test_allows_aligned_high_risk_rewording_when_the_state_is_preserved() -> None:
    original = "Revenue may increase in the next quarter. The contract permits the transfer with consent."
    rewritten = "Revenue might rise in the next quarter. The contract allows the transfer with consent."
    warnings = validate_preservation(original, rewritten, extract_semantics(original))
    assert not any(warning.kind in {"changed_claim_polarity", "changed_modal_obligation"} for warning in warnings)


def test_high_risk_guard_skips_claim_work_for_identical_content(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        validation,
        "split_sentences",
        lambda _text: pytest.fail("Identical text must bypass high-risk claim matching."),
    )
    assert validation._high_risk_claim_warnings("Revenue may increase.", "Revenue may increase.") == []


def test_high_risk_guard_rejects_a_far_reordered_inversion() -> None:
    target = "The contract permits the transfer only with prior written consent."
    filler = "Administrative note one. Administrative note two. Administrative note three. Administrative note four."
    original = f"{target} {filler}"
    rewritten = f"{filler} The contract prohibits the transfer only with prior written consent."
    warnings = validation._high_risk_claim_warnings(original, rewritten)
    assert any(warning.kind == "changed_claim_polarity" for warning in warnings)


def test_high_risk_guard_keeps_repeated_inversion_audit_bounded() -> None:
    original = "Revenue may increase in the next quarter. " * 100
    rewritten = original.replace("increase", "decrease")
    warnings = validation._high_risk_claim_warnings(original, rewritten)
    assert len(warnings) == 1
    assert warnings[0].kind == "changed_claim_polarity"
