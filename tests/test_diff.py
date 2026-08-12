from app.diff import create_diff


def test_repetitive_long_document_diff_is_non_recursive_and_complete() -> None:
    repeated = "# Bericht\n\n- Vollständiger Absatz mit Umlauten und Emoji 🧾.\n\n"
    original = "We would like to better understand the report.\n\n" + repeated * 250
    rewritten = "We would appreciate clarification on the report.\n\n" + repeated * 250
    report = create_diff(original, rewritten)
    assert any(line.startswith("- We would like") for line in report.sentence_diff)
    assert any(line.startswith("+ We would appreciate") for line in report.sentence_diff)
    assert report.lexical_similarity > 0.99
    assert report.surface_diversity < 0.01


def test_stable_diff_keeps_insertions_and_deletions_readable() -> None:
    report = create_diff("Alpha. Beta.", "Alpha. Gamma.")
    assert report.sentence_diff == ["  Alpha.", "- Beta.", "+ Gamma."]
