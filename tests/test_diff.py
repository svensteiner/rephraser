import time

from app.diff import create_diff


def test_repetitive_long_document_diff_is_bounded_and_explicit() -> None:
    repeated = "# Bericht\n\n- Vollständiger Absatz mit Umlauten und Emoji 🧾.\n\n"
    original = "We would like to better understand the report.\n\n" + repeated * 250
    rewritten = "We would appreciate clarification on the report.\n\n" + repeated * 250
    report = create_diff(original, rewritten)
    assert any(line.startswith("- We would like") for line in report.sentence_diff)
    assert any(line.startswith("+ We would appreciate") for line in report.sentence_diff)
    assert report.lexical_similarity > 0.99
    assert report.surface_diversity < 0.01
    assert report.detail_truncated is True
    assert report.comparison_complete is False
    assert report.truncation_reason


def test_stable_diff_keeps_insertions_and_deletions_readable() -> None:
    report = create_diff("Alpha. Beta.", "Alpha. Gamma.")
    assert report.sentence_diff == ["  Alpha.", "- Beta.", "+ Gamma."]
    assert report.detail_truncated is False
    assert report.comparison_complete is True
    assert report.comparison_method == "full_sequence"


def test_large_repeated_template_uses_bounded_honest_audit() -> None:
    template = "Die Prüfung umfasst die ausgewählten Bereiche. "
    original = template * 1_600
    rewritten = "Die Prüfung deckt die ausgewählten Bereiche ab. " + template * 1_599

    started = time.perf_counter()
    report = create_diff(original, rewritten)
    elapsed = time.perf_counter() - started

    assert elapsed < 5.0
    assert report.detail_truncated is True
    assert report.comparison_complete is False
    assert report.comparison_method == "bounded_prefix_suffix_and_token_overlap"
    assert report.truncation_reason
    assert report.model_dump()["comparison_complete"] is False
    assert report.model_dump()["truncation_reason"] == report.truncation_reason
    assert report.original_sentence_count == 1_600
    assert report.rewritten_sentence_count == 1_600
    assert report.original_word_count == 9_600
    assert report.rewritten_word_count == 9_601
    assert report.sentence_diff[0].startswith("! Detailed comparison is bounded")
    assert any(line.startswith("- Die Prüfung umfasst") for line in report.sentence_diff)
    assert any(line.startswith("+ Die Prüfung deckt") for line in report.sentence_diff)
    assert len(report.word_diff) < 20
    assert len(report.sentence_diff) < 20
