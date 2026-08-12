from app.models import TransformOptions
from app.pipeline import run_pipeline


def test_business_email_is_improved_instantly_without_changing_entities() -> None:
    text = (
        "We would like to better understand the accounts. "
        "You mentioned that Austria is the account holder.\n\n"
        "Could you please clarify:\n- Who controls the accounts?"
    )
    result = run_pipeline(text, TransformOptions(provider="fast-editor"))
    assert result.rewritten_text == (
        "We would appreciate clarification on the accounts. "
        "You noted that Austria is the account holder.\n\n"
        "Could you please clarify the following:\n- Who controls the accounts?"
    )
    assert result.audit.fact_preservation_warnings == []


def test_lowercase_phrase_inside_real_business_sentence_is_improved() -> None:
    text = "Regarding the accounts, we would like to better understand their legal ownership."
    result = run_pipeline(text, TransformOptions(provider="fast-editor"))
    assert result.rewritten_text == (
        "Regarding the accounts, we would appreciate clarification on their legal ownership."
    )
    assert result.audit.fact_preservation_warnings == []


def test_fast_editor_preserves_quotes_inline_code_and_fenced_code() -> None:
    text = (
        'She said "We would like to better understand this." `In order to`\n'
        "```text\nWe would like to better understand this.\n```\n"
        "In order to proceed, reply."
    )
    result = run_pipeline(text, TransformOptions(provider="fast-editor"))
    assert '"We would like to better understand this."' in result.rewritten_text
    assert "`In order to`" in result.rewritten_text
    assert "```text\nWe would like to better understand this.\n```" in result.rewritten_text
    assert result.rewritten_text.endswith("To proceed, reply.")


def test_fast_editor_preserves_sentence_initial_capitalization() -> None:
    text = "Due to the fact that it changed, we acted. Aufgrund der Tatsache, dass es sich änderte, handelten wir."
    result = run_pipeline(text, TransformOptions(provider="fast-editor"))
    assert result.rewritten_text == "Because it changed, we acted. Weil es sich änderte, handelten wir."


def test_fast_editor_preserves_front_matter_and_quoted_email_history() -> None:
    text = (
        "---\ntitle: We would like to better understand this\n---\n"
        "> We would like to better understand the old request.\n\n"
        "We would like to better understand the current request."
    )
    result = run_pipeline(text, TransformOptions(provider="fast-editor"))
    assert "title: We would like to better understand this" in result.rewritten_text
    assert "> We would like to better understand the old request." in result.rewritten_text
    assert result.rewritten_text.endswith("We would appreciate clarification on the current request.")


def test_fast_editor_preserves_more_markdown_code_and_link_destinations() -> None:
    text = (
        "~~~text\nWe would like to better understand fenced code.\n~~~\n"
        "    In order to preserve indented code\n"
        "[Label](https://example.com/In_order_to) and <https://example.com/In_order_to>\n"
        "In order to improve prose."
    )
    result = run_pipeline(text, TransformOptions(provider="fast-editor"))
    assert "We would like to better understand fenced code." in result.rewritten_text
    assert "    In order to preserve indented code" in result.rewritten_text
    assert "](https://example.com/In_order_to)" in result.rewritten_text
    assert "<https://example.com/In_order_to>" in result.rewritten_text
    assert result.rewritten_text.endswith("To improve prose.")
