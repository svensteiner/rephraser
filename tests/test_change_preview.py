import pytest

from app.change_preview import apply_change_selection, build_change_preview, build_change_segments


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


def test_each_change_can_be_selected_independently_without_losing_separators() -> None:
    original = "Wir möchten gerne prüfen. Zum jetzigen Zeitpunkt fehlt Beleg 17."
    rewritten = "Wir möchten prüfen. Derzeit fehlt Beleg 17."
    segments = build_change_segments(original, rewritten)

    assert len(segments) == 2
    assert apply_change_selection(original, segments, (False, False)) == original
    assert apply_change_selection(original, segments, (True, True)) == rewritten
    assert apply_change_selection(original, segments, (True, False)) == (
        "Wir möchten prüfen. Zum jetzigen Zeitpunkt fehlt Beleg 17."
    )
    assert apply_change_selection(original, segments, (False, True)) == (
        "Wir möchten gerne prüfen. Derzeit fehlt Beleg 17."
    )


def test_selection_preserves_markdown_unicode_and_insertions_exactly() -> None:
    original = "# Grüße 👩‍💻\n\n- Wert: 12,5 %"
    rewritten = "# Klare Grüße 👩‍💻\n\n- Wert: 12,5 % ✅"
    segments = build_change_segments(original, rewritten)

    assert apply_change_selection(original, segments, (True, False)) == (
        "# Klare Grüße 👩‍💻\n\n- Wert: 12,5 %"
    )
    assert apply_change_selection(original, segments, (False, True)) == (
        "# Grüße 👩‍💻\n\n- Wert: 12,5 % ✅"
    )


def test_invalid_selection_or_overlapping_segments_is_rejected() -> None:
    original = "Alt."
    segments = build_change_segments(original, "Neu.")
    with pytest.raises(ValueError, match="Selection count"):
        apply_change_selection(original, segments, ())
