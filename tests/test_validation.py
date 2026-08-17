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


def test_detects_cannot_moved_to_a_different_material_claim() -> None:
    original = "The account cannot transfer the shares, but the company will sell the assets."
    rewritten = "The account will transfer the shares, but the company cannot sell the assets."
    warnings = validate_preservation(original, rewritten, extract_semantics(original))
    assert any(warning.kind == "altered_negation_scope" for warning in warnings)


def test_allows_cannot_spelling_normalization_without_a_modal_false_positive() -> None:
    original = "The account cannot transfer the shares."
    rewritten = "The account can not transfer the shares."
    warnings = validate_preservation(original, rewritten, extract_semantics(original))
    assert not any(
        warning.kind in {"altered_negation", "altered_negation_scope", "changed_modal_obligation"}
        for warning in warnings
    )


def test_detects_uncertainty_moved_to_a_different_material_claim() -> None:
    original = "Revenue may increase, but costs will decline."
    rewritten = "Revenue will increase, but costs may decline."
    warnings = validate_preservation(original, rewritten, extract_semantics(original))
    assert any(warning.kind == "altered_uncertainty_scope" for warning in warnings)


@pytest.mark.parametrize(
    ("original", "rewritten"),
    [
        (
            "The company may sell the assets and the account cannot transfer the shares.",
            "The company cannot sell the assets and the account may transfer the shares.",
        ),
        (
            "Die Gesellschaft darf die Vermögenswerte verkaufen und das Konto kann die Anteile nicht übertragen.",
            "Die Gesellschaft kann die Vermögenswerte nicht verkaufen und das Konto darf die Anteile übertragen.",
        ),
    ],
)
def test_detects_state_relocation_across_repeated_subject_conjunctions(
    original: str,
    rewritten: str,
) -> None:
    warnings = validate_preservation(original, rewritten, extract_semantics(original))
    assert any(warning.kind == "altered_negation_scope" for warning in warnings)


@pytest.mark.parametrize(
    ("original", "rewritten", "warning_kind", "value"),
    [
        (
            "Alpha GmbH signed on 12.03.2026; Beta GmbH signed later.",
            "Alpha GmbH signed later; Beta GmbH signed on 12.03.2026.",
            "reassigned_date_context",
            "12.03.2026",
        ),
        (
            "Alpha GmbH reported EUR 10 revenue; Beta GmbH reported revenue.",
            "Alpha GmbH reported revenue; Beta GmbH reported EUR 10 revenue.",
            "reassigned_numeric_context",
            "EUR 10",
        ),
        (
            "Entity,Amount\nAlpha GmbH,10\nBeta GmbH,-",
            "Entity,Amount\nAlpha GmbH,-\nBeta GmbH,10",
            "reassigned_numeric_context",
            "10",
        ),
        (
            "Entity\tAmount\nAlpha GmbH\t10\nBeta GmbH\t-",
            "Entity\tAmount\nAlpha GmbH\t-\nBeta GmbH\t10",
            "reassigned_numeric_context",
            "10",
        ),
    ],
)
def test_detects_lone_value_reassigned_between_clear_entities(
    original: str,
    rewritten: str,
    warning_kind: str,
    value: str,
) -> None:
    warnings = validate_preservation(original, rewritten, extract_semantics(original))
    assert any(warning.kind == warning_kind and warning.value == value for warning in warnings)


def test_allows_lone_value_rewording_with_the_same_clear_entity() -> None:
    original = "Alpha GmbH signed on 12.03.2026."
    rewritten = "On 12.03.2026, Alpha GmbH signed."
    warnings = validate_preservation(original, rewritten, extract_semantics(original))
    assert not any(warning.kind == "reassigned_date_context" for warning in warnings)


@pytest.mark.parametrize(
    ("original", "rewritten", "warning_kind"),
    [
        (
            "Revenue was 10 million euros in Q1.",
            "Revenue was 10 billion euros in Q1.",
            "changed_monetary_scale",
        ),
        (
            "The interest rate increased by 10 basis points.",
            "The interest rate increased by 10 percentage points.",
            "changed_quantity_unit",
        ),
        (
            "Payment is due within 30 days.",
            "Payment is due within 30 months.",
            "changed_quantity_unit",
        ),
        (
            "The company issued 10 million shares.",
            "The company issued 10 billion shares.",
            "changed_quantity_unit",
        ),
    ],
)
def test_detects_written_money_and_quantity_unit_or_scale_changes(
    original: str,
    rewritten: str,
    warning_kind: str,
) -> None:
    warnings = validate_preservation(original, rewritten, extract_semantics(original))
    assert any(warning.kind == warning_kind for warning in warnings)


def test_allows_equivalent_quantity_unit_spelling() -> None:
    original = "The interest rate increased by 10 bp."
    rewritten = "The interest rate increased by 10 basis points."
    warnings = validate_preservation(original, rewritten, extract_semantics(original))
    assert not any(warning.kind == "changed_quantity_unit" for warning in warnings)


@pytest.mark.parametrize(
    ("original", "rewritten", "warning_kind", "marker"),
    [
        (
            "The value must exceed EUR 10.",
            "The value must be below EUR 10.",
            "changed_claim_comparator",
            "strict threshold: exceed -> below",
        ),
        (
            "Payment is due no later than 31 March 2026.",
            "Payment is due no earlier than 31 March 2026.",
            "changed_claim_comparator",
            "deadline: no later than -> no earlier than",
        ),
        (
            "The audit passed.",
            "The audit failed.",
            "changed_material_status",
            "audit outcome: passed -> failed",
        ),
        (
            "The control is compliant with the policy.",
            "The control is non-compliant with the policy.",
            "changed_material_status",
            "compliance status: compliant -> non-compliant",
        ),
        (
            "The company reported a profit.",
            "The company reported a loss.",
            "changed_claim_polarity",
            "financial result: profit -> loss",
        ),
    ],
)
def test_detects_explicit_high_risk_legal_financial_pairs(
    original: str,
    rewritten: str,
    warning_kind: str,
    marker: str,
) -> None:
    warnings = validate_preservation(original, rewritten, extract_semantics(original))
    assert any(warning.kind == warning_kind and warning.value == marker for warning in warnings)


def test_detects_at_least_to_at_most_comparator_inversion() -> None:
    original = "At least 10 reports are required."
    rewritten = "At most 10 reports are required."
    warnings = validate_preservation(original, rewritten, extract_semantics(original))
    assert any(
        warning.kind == "changed_claim_comparator"
        and warning.value == "threshold: at least -> at most"
        for warning in warnings
    )


def test_detects_german_threshold_inversion() -> None:
    original = "Mindestens 10 Berichte sind erforderlich."
    rewritten = "Höchstens 10 Berichte sind erforderlich."
    warnings = validate_preservation(original, rewritten, extract_semantics(original))
    assert any(
        warning.kind == "changed_claim_comparator"
        and warning.value == "threshold: mindestens -> höchstens"
        for warning in warnings
    )


def test_detects_short_material_status_reversal_and_deletion() -> None:
    reversed_status = validate_preservation("Active.", "Inactive.", extract_semantics("Active."))
    approval_reversal = validate_preservation("Approved.", "Rejected.", extract_semantics("Approved."))
    deleted_status = validate_preservation(
        "The account is active.", "The account was reviewed.", extract_semantics("The account is active.")
    )
    assert any(warning.kind == "changed_material_status" for warning in reversed_status)
    assert any(warning.kind == "changed_material_status" for warning in approval_reversal)
    assert any(
        warning.kind in {"changed_material_status", "missing_material_status_claim"}
        for warning in deleted_status
    )


def test_allows_aligned_high_risk_rewording_when_the_state_is_preserved() -> None:
    original = "Revenue may increase in the next quarter. The contract permits the transfer with consent."
    rewritten = "Revenue might rise in the next quarter. The contract allows the transfer with consent."
    warnings = validate_preservation(original, rewritten, extract_semantics(original))
    assert not any(warning.kind in {"changed_claim_polarity", "changed_modal_obligation"} for warning in warnings)


@pytest.mark.parametrize(
    ("original", "rewritten"),
    [
        ("Acme must pay Beta.", "Beta must pay Acme."),
        ("Acme muss Beta zahlen.", "Beta muss Acme zahlen."),
    ],
)
def test_detects_swapped_payer_and_recipient_roles(original: str, rewritten: str) -> None:
    warnings = validate_preservation(original, rewritten, extract_semantics(original))
    assert any(warning.kind == "swapped_payment_obligation_roles" for warning in warnings)


def test_allows_an_equivalent_explicit_payment_obligation() -> None:
    original = "Acme must pay Beta."
    rewritten = "Acme is required to pay Beta."
    warnings = validate_preservation(original, rewritten, extract_semantics(original))
    assert not any(warning.kind == "swapped_payment_obligation_roles" for warning in warnings)


@pytest.mark.parametrize(
    ("original", "rewritten"),
    [
        (
            "Austria is the account holder; Belgium is the beneficial owner.",
            "Belgium is the account holder; Austria is the beneficial owner.",
        ),
        (
            "Acme is the borrower; Beta is the guarantor.",
            "Beta is the borrower; Acme is the guarantor.",
        ),
        (
            "Österreich ist der Kontoinhaber; Belgien ist der wirtschaftlich Berechtigte.",
            "Belgien ist der Kontoinhaber; Österreich ist der wirtschaftlich Berechtigte.",
        ),
    ],
)
def test_detects_swapped_explicit_material_role_assignments(
    original: str,
    rewritten: str,
) -> None:
    warnings = validate_preservation(original, rewritten, extract_semantics(original))
    assert any(warning.kind == "swapped_material_role_assignments" for warning in warnings)


def test_detects_changed_explicit_material_role_assignment() -> None:
    original = "The borrower is Acme."
    rewritten = "The guarantor is Acme."
    warnings = validate_preservation(original, rewritten, extract_semantics(original))
    assert any(warning.kind == "changed_material_role_assignment" for warning in warnings)


@pytest.mark.parametrize(
    ("original", "rewritten"),
    [
        ("Austria is the account holder.", "Belgium holds the account."),
        ("The borrower is Acme.", "Beta took out the loan."),
    ],
)
def test_detects_reassignment_through_a_common_material_role_equivalent(
    original: str,
    rewritten: str,
) -> None:
    warnings = validate_preservation(original, rewritten, extract_semantics(original))
    assert any(warning.kind == "changed_material_role_assignment" for warning in warnings)


def test_fails_closed_when_a_material_role_assignment_cannot_be_verified() -> None:
    original = "Austria is the account holder."
    rewritten = "Austria manages the account."
    warnings = validate_preservation(original, rewritten, extract_semantics(original))
    warning = next(
        warning for warning in warnings if warning.kind == "unverified_material_role_assignment"
    )
    assert warning.value == "account_holder: austria"


def test_allows_equivalent_explicit_material_role_rephrasing() -> None:
    original = "Austria is the account holder; Belgium is the beneficial owner."
    rewritten = "The account holder is Austria; Belgium remains the beneficial owner."
    warnings = validate_preservation(original, rewritten, extract_semantics(original))
    assert not any(
        warning.kind in {"swapped_material_role_assignments", "changed_material_role_assignment"}
        for warning in warnings
    )


def test_detects_numeric_markdown_table_cell_and_header_order_changes() -> None:
    original = "| Entity | Q1 | Q2 |\n| --- | ---: | ---: |\n| Acme | 10 | 20 |"
    swapped_values = "| Entity | Q1 | Q2 |\n| --- | ---: | ---: |\n| Acme | 20 | 10 |"
    swapped_headers = "| Entity | Q2 | Q1 |\n| --- | ---: | ---: |\n| Acme | 10 | 20 |"

    for rewritten in (swapped_values, swapped_headers):
        warnings = validate_preservation(original, rewritten, extract_semantics(original))
        assert any(warning.kind == "altered_table_numeric_layout" for warning in warnings)


def test_detects_reporting_quarter_and_monetary_scale_changes() -> None:
    original = "Revenue for Q1 was EUR 10 million."
    changed_quarter = validate_preservation(
        original,
        "Revenue for Q2 was EUR 10 million.",
        extract_semantics(original),
    )
    changed_scale = validate_preservation(
        original,
        "Revenue for Q1 was EUR 10 billion.",
        extract_semantics(original),
    )
    preserved = validate_preservation(
        original,
        "Revenue for first quarter was EUR 10m.",
        extract_semantics(original),
    )
    german_quarter = validate_preservation(
        "Im 1. Quartal betrug der Umsatz EUR 10 Mio.",
        "Im 2. Quartal betrug der Umsatz EUR 10 Mio.",
        extract_semantics("Im 1. Quartal betrug der Umsatz EUR 10 Mio."),
    )

    assert any(warning.kind == "changed_reporting_period" for warning in changed_quarter)
    assert any(warning.kind == "changed_monetary_scale" for warning in changed_scale)
    assert any(warning.kind == "changed_reporting_period" for warning in german_quarter)
    assert not any(
        warning.kind in {"changed_reporting_period", "changed_monetary_scale"}
        for warning in preserved
    )


def test_detects_spelled_german_reporting_quarter_change_and_allows_equivalence() -> None:
    original = "Im ersten Quartal betrug der Umsatz EUR 10 Mio."
    changed = validate_preservation(
        original,
        "Im zweiten Quartal betrug der Umsatz EUR 10 Mio.",
        extract_semantics(original),
    )
    equivalent = validate_preservation(
        original,
        "Im Q1 betrug der Umsatz EUR 10 Mio.",
        extract_semantics(original),
    )

    assert any(
        warning.kind == "changed_reporting_period" and warning.value == "Q1 -> Q2"
        for warning in changed
    )
    assert not any(warning.kind == "changed_reporting_period" for warning in equivalent)


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


def test_high_risk_guard_fails_closed_when_its_risk_claim_budget_is_exceeded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(validation, "HIGH_RISK_MAX_RISK_CLAIMS", 2)
    original = "The service is active. " * 3
    rewritten = original.replace("The service", "The system", 1)
    warnings = validation._high_risk_claim_warnings(original, rewritten)
    assert len(warnings) == 1
    assert warnings[0].kind == "high_risk_claim_scan_limit"
