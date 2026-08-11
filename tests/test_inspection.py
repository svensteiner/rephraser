from app.inspection import inspect_text, split_sentences


def test_unicode_markdown_and_lists() -> None:
    report = inspect_text("# Grüße\n\n- A\u200b\n- B\u2066")
    assert report.headings == ["# Grüße"]
    assert report.list_items == 2
    assert [f.code_point for f in report.characters] == ["U+200B", "U+2066"]
    assert report.characters[-1].kind == "unknown_format_character"


def test_german_named_date_does_not_split_sentence() -> None:
    sentences = split_sentences("Am 3. März 2026 war der Wert stabil. Danach stieg er.")
    assert sentences == ["Am 3. März 2026 war der Wert stabil.", "Danach stieg er."]


def test_sentence_split_keeps_closing_quote_with_preceding_sentence() -> None:
    assert split_sentences('Er sagte: "Hallo." Danach ging er.') == [
        'Er sagte: "Hallo."',
        "Danach ging er.",
    ]
