from __future__ import annotations

from collections import Counter
import difflib
import re
from typing import Any

from .inspection import split_sentences
from .models import DiffReport


# SequenceMatcher is useful for a readable, detailed diff on ordinary
# business texts. Its worst case, however, is quadratic. Repeated templates or
# a pasted large document can otherwise make audit generation appear to hang.
# Keep the full comparison comfortably below that risk zone and use a
# transparent summary outside it.
_MAX_FULL_SEQUENCE_CHARACTERS = 16_000
_MAX_FULL_SEQUENCE_ITEMS = 1_200
_MAX_FULL_SENTENCE_CHARACTERS = 2_000
_MAX_DETAILED_MIDDLE_ITEMS = 400
_MAX_DETAILED_MIDDLE_CHARACTERS = 16_000
_MAX_SAMPLE_ITEMS = 3
_MAX_SAMPLE_ITEM_CHARACTERS = 320


def _stable_diff(old_items: list[str], new_items: list[str]) -> list[str]:
    """Return an ndiff-like representation without Differ's recursive matching."""
    lines: list[str] = []
    matcher = difflib.SequenceMatcher(None, old_items, new_items, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            lines.extend(f"  {item}" for item in old_items[i1:i2])
        elif tag == "delete":
            lines.extend(f"- {item}" for item in old_items[i1:i2])
        elif tag == "insert":
            lines.extend(f"+ {item}" for item in new_items[j1:j2])
        else:
            lines.extend(f"- {item}" for item in old_items[i1:i2])
            lines.extend(f"+ {item}" for item in new_items[j1:j2])
    return lines


def _has_high_repetition(items: list[str]) -> bool:
    """Identify sequences that are unsafe for an unrestricted matcher.

    A common word in a normal document is not enough to trigger the fallback.
    This only catches strongly repeated material such as copied templates.
    """
    if len(items) < 128:
        return False
    most_common = Counter(items).most_common(1)[0][1]
    return most_common >= 32 and most_common * 10 >= len(items)


def _max_item_length(old_items: list[str], new_items: list[str]) -> int:
    return max(
        max((len(item) for item in old_items), default=0),
        max((len(item) for item in new_items), default=0),
    )


def _requires_bounded_comparison(
    original: str,
    rewritten: str,
    old_words: list[str],
    new_words: list[str],
    old_sentences: list[str],
    new_sentences: list[str],
) -> bool:
    return (
        max(len(original), len(rewritten)) > _MAX_FULL_SEQUENCE_CHARACTERS
        or max(len(old_words), len(new_words), len(old_sentences), len(new_sentences))
        > _MAX_FULL_SEQUENCE_ITEMS
        or _max_item_length(old_sentences, new_sentences) > _MAX_FULL_SENTENCE_CHARACTERS
        or _has_high_repetition(old_words)
        or _has_high_repetition(new_words)
        or _has_high_repetition(old_sentences)
        or _has_high_repetition(new_sentences)
    )


def _common_edges(old_items: list[str], new_items: list[str]) -> tuple[int, int]:
    """Return exact common prefix and suffix lengths in linear time."""
    prefix = 0
    limit = min(len(old_items), len(new_items))
    while prefix < limit and old_items[prefix] == new_items[prefix]:
        prefix += 1

    suffix = 0
    old_remaining = len(old_items) - prefix
    new_remaining = len(new_items) - prefix
    while suffix < old_remaining and suffix < new_remaining:
        if old_items[len(old_items) - suffix - 1] != new_items[len(new_items) - suffix - 1]:
            break
        suffix += 1
    return prefix, suffix


def _is_safe_middle(old_items: list[str], new_items: list[str]) -> bool:
    item_count = len(old_items) + len(new_items)
    if item_count > _MAX_DETAILED_MIDDLE_ITEMS:
        return False
    middle_characters = sum(len(item) for item in old_items) + sum(
        len(item) for item in new_items
    )
    if middle_characters > _MAX_DETAILED_MIDDLE_CHARACTERS:
        return False
    if _max_item_length(old_items, new_items) > _MAX_FULL_SENTENCE_CHARACTERS:
        return False
    return not _has_high_repetition(old_items) and not _has_high_repetition(new_items)


def _shorten_item(item: str) -> str:
    """Keep a summary useful without letting one huge token fill the audit."""
    compact = item.rstrip("\r\n")
    if len(compact) <= _MAX_SAMPLE_ITEM_CHARACTERS:
        return compact
    omitted = len(compact) - _MAX_SAMPLE_ITEM_CHARACTERS
    return f"{compact[:_MAX_SAMPLE_ITEM_CHARACTERS]} … [{omitted} characters omitted]"


def _sample_lines(prefix: str, items: list[str]) -> list[str]:
    if not items:
        return []
    if len(items) <= _MAX_SAMPLE_ITEMS:
        selected = items
    else:
        selected = [*items[:2], items[-1]]
    lines = [f"{prefix} {_shorten_item(item)}" for item in selected]
    omitted = len(items) - len(selected)
    if omitted:
        lines.insert(-1, f"! [{omitted} additional item(s) omitted from this excerpt]")
    return lines


def _bounded_diff(
    old_items: list[str],
    new_items: list[str],
    *,
    label: str,
) -> tuple[list[str], bool]:
    """Return a bounded excerpt and whether its changed middle was fully matched."""
    prefix, suffix = _common_edges(old_items, new_items)
    old_end = len(old_items) - suffix if suffix else len(old_items)
    new_end = len(new_items) - suffix if suffix else len(new_items)
    old_middle = old_items[prefix:old_end]
    new_middle = new_items[prefix:new_end]

    lines = [
        "! Detailed comparison is bounded for a long or highly repetitive input; "
        "this is an excerpt, not a complete line-by-line diff."
    ]
    if prefix:
        lines.append(f"  [{prefix} unchanged {label}(s) before the excerpt omitted]")
    if _is_safe_middle(old_middle, new_middle):
        lines.extend(_stable_diff(old_middle, new_middle))
        middle_complete = True
    else:
        lines.append(
            f"! Changed {label} region summarized: {len(old_middle)} original and "
            f"{len(new_middle)} rewritten item(s)."
        )
        lines.extend(_sample_lines("-", old_middle))
        lines.extend(_sample_lines("+", new_middle))
        middle_complete = False
    if suffix:
        lines.append(f"  [{suffix} unchanged {label}(s) after the excerpt omitted]")
    return lines, middle_complete


def _token_overlap_similarity(old_tokens: list[str], new_tokens: list[str]) -> float:
    """Compute an exact bag-of-tokens overlap in linear time for bounded mode."""
    if not old_tokens and not new_tokens:
        return 1.0
    if not old_tokens or not new_tokens:
        return 0.0
    overlap = sum((Counter(old_tokens) & Counter(new_tokens)).values())
    return overlap / max(len(old_tokens), len(new_tokens))


def _sentence_changes(
    old_sentences: list[str], new_sentences: list[str]
) -> tuple[list[str], list[str], list[dict[str, Any]]]:
    """Collect sentence-level changes only for an already bounded-safe sequence."""
    added: list[str] = []
    removed: list[str] = []
    rewritten_items: list[dict[str, Any]] = []
    matcher = difflib.SequenceMatcher(None, old_sentences, new_sentences)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "insert":
            added.extend(new_sentences[j1:j2])
        elif tag == "delete":
            removed.extend(old_sentences[i1:i2])
        elif tag == "replace":
            old, new = old_sentences[i1:i2], new_sentences[j1:j2]
            for left, right in zip(old, new):
                # _is_safe_middle guarantees a small enough item for this
                # character-level similarity check.
                similarity = difflib.SequenceMatcher(None, left, right).ratio()
                rewritten_items.append(
                    {"original": left, "rewritten": right, "similarity": round(similarity, 3)}
                )
            if len(old) > len(new):
                removed.extend(old[len(new):])
            if len(new) > len(old):
                added.extend(new[len(old):])
    return added, removed, [item for item in rewritten_items if item["similarity"] < 0.7]


def create_diff(original: str, rewritten: str) -> DiffReport:
    old_words = re.findall(r"\S+\s*", original)
    new_words = re.findall(r"\S+\s*", rewritten)
    old_tokens = [token.casefold() for token in re.findall(r"\b\w+\b", original)]
    new_tokens = [token.casefold() for token in re.findall(r"\b\w+\b", rewritten)]
    old_sentences = split_sentences(original)
    new_sentences = split_sentences(rewritten)
    counts = {
        "original_word_count": len(old_words),
        "rewritten_word_count": len(new_words),
        "original_sentence_count": len(old_sentences),
        "rewritten_sentence_count": len(new_sentences),
    }

    if original == rewritten:
        return DiffReport(
            word_diff=[],
            sentence_diff=[],
            lexical_similarity=1.0,
            surface_diversity=0.0,
            added_sentences=[],
            removed_sentences=[],
            substantially_rewritten_sentences=[],
            comparison_method="exact_text_equality",
            **counts,
        )

    if _requires_bounded_comparison(
        original, rewritten, old_words, new_words, old_sentences, new_sentences
    ):
        word_diff, _ = _bounded_diff(old_words, new_words, label="word")
        sentence_diff, sentence_middle_complete = _bounded_diff(
            old_sentences, new_sentences, label="sentence"
        )
        # Preserve sentence-level details when the changed region itself is
        # small. Otherwise leave these lists empty rather than claiming that a
        # sampled excerpt represents every added, removed, or rewritten item.
        sentence_prefix, sentence_suffix = _common_edges(old_sentences, new_sentences)
        old_end = (
            len(old_sentences) - sentence_suffix if sentence_suffix else len(old_sentences)
        )
        new_end = (
            len(new_sentences) - sentence_suffix if sentence_suffix else len(new_sentences)
        )
        old_middle = old_sentences[sentence_prefix:old_end]
        new_middle = new_sentences[sentence_prefix:new_end]
        if sentence_middle_complete and _is_safe_middle(old_middle, new_middle):
            added, removed, rewritten_items = _sentence_changes(old_middle, new_middle)
        else:
            added, removed, rewritten_items = [], [], []
        lexical_similarity = _token_overlap_similarity(old_tokens, new_tokens)
        reason = (
            "Detailed sequence comparison was bounded because the input is long or highly "
            "repetitive. Counts and lexical token overlap cover the whole input; displayed "
            "diff lines are an excerpt and may not list every change."
        )
        # The prefix/suffix check can identify some complete small middle
        # changes, but the report intentionally uses a bounded rendering and
        # aggregate similarity, so it must never claim a full sequence audit.
        return DiffReport(
            word_diff=word_diff,
            sentence_diff=sentence_diff,
            lexical_similarity=round(lexical_similarity, 3),
            surface_diversity=round(1.0 - lexical_similarity, 3),
            added_sentences=added,
            removed_sentences=removed,
            substantially_rewritten_sentences=rewritten_items,
            detail_truncated=True,
            comparison_complete=False,
            comparison_method="bounded_prefix_suffix_and_token_overlap",
            truncation_reason=reason,
            **counts,
        )

    lexical_similarity = difflib.SequenceMatcher(None, old_tokens, new_tokens).ratio()
    word_diff = _stable_diff(old_words, new_words)
    sentence_diff = _stable_diff(old_sentences, new_sentences)
    added, removed, rewritten_items = _sentence_changes(old_sentences, new_sentences)
    return DiffReport(
        word_diff=word_diff,
        sentence_diff=sentence_diff,
        lexical_similarity=round(lexical_similarity, 3),
        surface_diversity=round(1.0 - lexical_similarity, 3),
        added_sentences=added,
        removed_sentences=removed,
        substantially_rewritten_sentences=rewritten_items,
        **counts,
    )
