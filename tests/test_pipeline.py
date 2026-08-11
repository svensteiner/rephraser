from app.models import TransformOptions
from app.pipeline import run_pipeline
from app.providers.base import EditorialProvider


class UnsafeMistralStub(EditorialProvider):
    name = "mistral-test"

    def rewrite(self, text, constraints, options):
        return text.replace("12,5 %", "15 Prozent") + " Neue unbelegte Behauptung."


class HarmlessUrlFormattingStub(EditorialProvider):
    name = "mistral-test"

    def rewrite(self, text, constraints, options):
        return text.replace("Die Marge betrug", "Die Marge lag").replace(
            "https://example.com/x", "<https://example.com/x>"
        )


class UnavailableMistralStub(EditorialProvider):
    name = "mistral-test"

    def rewrite(self, text, constraints, options):
        from app.providers.base import ProviderError

        raise ProviderError("timed out")


class MeaningChangingStub(EditorialProvider):
    name = "mistral-test"

    def rewrite(self, text, constraints, options):
        return "Der Umsatz wird steigen. Der Gewinn wird sinken."


class MarkdownDamagingStub(EditorialProvider):
    name = "mistral-test"

    def rewrite(self, text, constraints, options):
        return text.replace("# Titel", "Titel").replace("- Punkt", "Punkt")


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
    for field in ["original_hash", "output_hash", "timestamp", "pipeline_version",
                  "requested_provider", "applied_provider", "options", "inspection",
                  "inspection_after",
                  "semantic_constraints", "transformations", "fact_preservation_warnings",
                  "quality_metrics_before", "quality_metrics_after"]:
        assert field in data
    assert "ai_probability" not in data


def test_audit_records_before_after_unicode_and_explicit_edit_offsets() -> None:
    text = "A\u200bB\u200b C\u00a0D"
    result = run_pipeline(text, TransformOptions(provider="rules"))
    before = {item.code_point: item for item in result.audit.inspection.character_summary}
    after = {item.code_point: item for item in result.audit.inspection_after.character_summary}
    assert before["U+200B"].count == 2
    assert before["U+200B"].positions == [1, 3]
    assert before["U+00A0"].count == 1
    assert "U+200B" not in after
    assert "U+00A0" not in after
    assert result.audit.transformations
    for change in result.audit.transformations:
        assert change.before == text[change.original_start:change.original_end]
        assert change.after == result.rewritten_text[change.rewritten_start:change.rewritten_end]


def test_unknown_format_character_is_visible_before_and_after_because_it_is_preserved() -> None:
    result = run_pipeline("A\u2066B", TransformOptions(provider="rules"))
    assert result.rewritten_text == "A\u2066B"
    assert result.audit.inspection.character_summary[0].code_point == "U+2066"
    assert result.audit.inspection_after.character_summary[0].code_point == "U+2066"


def test_only_leading_bom_is_removed_and_mid_text_bom_is_reported() -> None:
    result = run_pipeline("\ufeffA\ufeffB", TransformOptions(provider="rules"))
    assert result.rewritten_text == "A\ufeffB"
    assert result.audit.inspection_after.character_summary[0].code_point == "U+FEFF"
    assert result.audit.inspection_after.character_summary[0].positions == [1]
    leading = result.audit.transformations[0]
    assert leading.before == "\ufeff"
    assert leading.reason == "Remove leading Unicode byte-order mark"
    assert leading.code_points_before == ["U+FEFF"]


def test_unicode_cleanup_audit_has_specific_reasons_and_code_points() -> None:
    result = run_pipeline("A\u200bB\u00a0C\u00adD", TransformOptions(provider="rules"))
    reasons = {change.reason for change in result.audit.transformations}
    assert "Remove zero-width space copy/paste artifact" in reasons
    assert "Replace non-breaking space with regular space" in reasons
    assert "Remove invisible soft-hyphen copy/paste artifact" in reasons
    assert all(change.code_points_before for change in result.audit.transformations)


def test_unsafe_mistral_result_is_rejected_safely() -> None:
    text = "Die Marge betrug 12,5 %."
    result = run_pipeline(text, TransformOptions(provider="rules"), provider=UnsafeMistralStub())
    assert result.rewritten_text == text
    assert any(warning.kind == "rewrite_rejected" for warning in result.audit.fact_preservation_warnings)


def test_harmless_added_url_autolink_is_repaired_before_validation() -> None:
    text = "Die Marge betrug 12,5 %. Quelle: https://example.com/x"
    result = run_pipeline(
        text,
        TransformOptions(provider="rules"),
        provider=HarmlessUrlFormattingStub(),
    )
    assert result.rewritten_text == "Die Marge lag 12,5 %. Quelle: https://example.com/x"
    assert result.audit.fact_preservation_warnings == []


def test_unavailable_mistral_returns_safe_result_instead_of_hanging_or_failing() -> None:
    text = "Grüße\u00a0aus Wien – 12,5 %."
    result = run_pipeline(text, TransformOptions(provider="rules"), provider=UnavailableMistralStub())
    assert result.rewritten_text == "Grüße aus Wien – 12,5 %."
    assert any(w.kind == "provider_unavailable" for w in result.audit.fact_preservation_warnings)


def test_meaning_changing_rewrite_is_rejected() -> None:
    text = ("Der Umsatz dürfte steigen. Der Gewinn wird nicht sinken. "
            "Die langfristigen Lieferverträge sichern stabile Beschaffungskosten.")
    result = run_pipeline(text, TransformOptions(provider="rules"), provider=MeaningChangingStub())
    assert result.rewritten_text == text
    assert any(w.kind == "rewrite_rejected" for w in result.audit.fact_preservation_warnings)
    assert result.audit.requested_provider == "mistral-test"
    assert result.audit.applied_provider == "rules"
    rejection = next(w for w in result.audit.fact_preservation_warnings if w.kind == "rewrite_rejected")
    assert "altered_negation" in rejection.value
    assert result.audit.output_hash == result.audit.original_hash


def test_markdown_damaging_rewrite_is_rejected() -> None:
    text = "# Titel\n\n- Punkt"
    result = run_pipeline(text, TransformOptions(provider="rules"), provider=MarkdownDamagingStub())
    assert result.rewritten_text == text
    assert any(w.kind == "rewrite_rejected" for w in result.audit.fact_preservation_warnings)


def test_substantial_rules_preserve_blank_lines_inside_fenced_code() -> None:
    text = "Vorher\n\n\nNachher\n```text\na\n\n\n\nb\n```\n"
    result = run_pipeline(text, TransformOptions(provider="rules", rewrite_strength="substantial"))
    assert result.rewritten_text == "Vorher\n\nNachher\n```text\na\n\n\n\nb\n```\n"
