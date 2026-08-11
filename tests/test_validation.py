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
