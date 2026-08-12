from app.change_preview import build_change_preview


def _highlighted(text: str, ranges: tuple[tuple[int, int], ...]) -> str:
    return "|".join(text[start:end] for start, end in ranges)


def test_change_preview_marks_replacements_on_both_sides() -> None:
    original = "Das ist ein alter Satz."
    rewritten = "Das ist ein klarer Satz."

    preview = build_change_preview(original, rewritten)

    assert preview.change_groups == 1
    assert _highlighted(original, preview.original_ranges) == "alter"
    assert _highlighted(rewritten, preview.rewritten_ranges) == "klarer"


def test_change_preview_handles_insertions_unicode_markdown_and_emoji() -> None:
    original = "# Grüße aus Wien\n\n- Betrag: 12,5 % 👩‍💻"
    rewritten = "# Klare Grüße aus Wien\n\n- Betrag: 12,5 % 👩‍💻 ✅"

    preview = build_change_preview(original, rewritten)

    highlighted = _highlighted(rewritten, preview.rewritten_ranges)
    assert "Klare" in highlighted
    assert "✅" in highlighted
    assert _highlighted(original, preview.original_ranges) == ""
    assert "12,5 %" in rewritten
    assert "👩‍💻" in rewritten


def test_change_preview_is_stable_for_long_repetitive_documents() -> None:
    repeated = "Absatz mit gleichem Inhalt und 12,5 %.\n\n" * 300
    original = "Alte Überschrift\n\n" + repeated
    rewritten = "Klare Überschrift\n\n" + repeated

    preview = build_change_preview(original, rewritten)

    assert preview.change_groups == 1
    assert _highlighted(original, preview.original_ranges) == "Alte"
    assert _highlighted(rewritten, preview.rewritten_ranges) == "Klare"
