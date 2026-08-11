from app.models import TransformOptions
from app.pipeline import run_pipeline
from app.providers.base import EditorialProvider


class UnsafeMistralStub(EditorialProvider):
    name = "mistral-test"

    def rewrite(self, text, constraints, options):
        return text.replace("12,5 %", "15 Prozent") + " Neue unbelegte Behauptung."


def test_rules_preserve_protected_content_and_umlauts() -> None:
    text = ('Es ist wichtig zu beachten, dass Jörg Müller am 31.12.2025 „Grüße“ sagte. '
            'Der Wert war 1.250,50 EUR (12,5 %). https://example.com/x')
    result = run_pipeline(text, TransformOptions(provider="rules"))
    for value in ["Jörg Müller", "31.12.2025", "„Grüße“", "1.250,50 EUR", "12,5 %", "https://example.com/x"]:
        assert value in result.rewritten_text
    assert result.audit.fact_preservation_warnings == []


def test_rules_do_not_break_german_filler_construction() -> None:
    text = "Es ist wichtig zu beachten, dass der Wert stabil bleibt."
    result = run_pipeline(text, TransformOptions(provider="rules"))
    assert result.rewritten_text == text


def test_markdown_bullets_survive() -> None:
    result = run_pipeline("# Titel\n\n- Bitcoin\n- Ethereum", TransformOptions(provider="rules"))
    assert result.rewritten_text.startswith("# Titel")
    assert "- Bitcoin\n- Ethereum" in result.rewritten_text


def test_markdown_code_hard_break_emoji_and_unknown_cf_survive() -> None:
    text = "Zeile mit Break  \n```text\nEs ist wichtig zu beachten, dass  x  y\n```\nFamilie 👨‍👩‍👧 \u2066"
    result = run_pipeline(text, TransformOptions(provider="rules", rewrite_strength="substantial"))
    assert "Break  \n" in result.rewritten_text
    assert "Es ist wichtig zu beachten, dass  x  y" in result.rewritten_text
    assert "👨‍👩‍👧" in result.rewritten_text
    assert "\u2066" in result.rewritten_text


def test_long_german_compound_sentence_is_processed() -> None:
    text = ("Die Wirtschaftsprüfungsberichterstattungsverordnung verlangt eine sorgfältige "
            "Dokumentation, weil die Unternehmensfortführungsprognose für Kreditentscheidungen "
            "wesentlich sein kann und möglicherweise zusätzliche Nachweise erfordert.")
    result = run_pipeline(text, TransformOptions(provider="rules", rewrite_strength="substantial"))
    assert "Wirtschaftsprüfungsberichterstattungsverordnung" in result.rewritten_text
    assert result.audit.semantic_constraints.uncertainties


def test_audit_has_required_fields_and_no_ai_score() -> None:
    result = run_pipeline("Ein klarer Satz.")
    data = result.audit.model_dump(mode="json")
    for field in ["original_hash", "timestamp", "pipeline_version", "inspection",
                  "semantic_constraints", "transformations", "fact_preservation_warnings",
                  "quality_metrics_before", "quality_metrics_after"]:
        assert field in data
    assert "ai_probability" not in data


def test_unsafe_mistral_result_is_rejected_safely() -> None:
    text = "Die Marge betrug 12,5 %."
    result = run_pipeline(text, TransformOptions(provider="rules"), provider=UnsafeMistralStub())
    assert result.rewritten_text == text
    assert any(warning.kind == "rewrite_rejected" for warning in result.audit.fact_preservation_warnings)
