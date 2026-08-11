from app.repair import repair_protected_formatting
from app.semantic import extract_semantics


def test_existing_markdown_autolink_is_not_changed() -> None:
    original = "Quelle: <https://example.com/x>"
    assert repair_protected_formatting(original, original, extract_semantics(original)) == original


def test_only_exact_protected_url_wrapper_is_removed() -> None:
    original = "Quelle: https://example.com/x"
    rewritten = "Quelle: <https://example.com/x> und <anderer Text>"
    assert repair_protected_formatting(original, rewritten, extract_semantics(original)) == (
        "Quelle: https://example.com/x und <anderer Text>"
    )
