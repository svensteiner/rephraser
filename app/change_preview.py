"""Stable, Unicode-safe change ranges for the native review window."""

from __future__ import annotations

from dataclasses import dataclass
import difflib
import re


TOKEN = re.compile(r"\s+|\w+|[^\w\s]", re.UNICODE)


@dataclass(frozen=True, slots=True)
class ChangePreview:
    original_ranges: tuple[tuple[int, int], ...]
    rewritten_ranges: tuple[tuple[int, int], ...]
    change_groups: int


def _tokens_with_spans(text: str) -> tuple[list[str], list[tuple[int, int]]]:
    matches = list(TOKEN.finditer(text))
    return [match.group() for match in matches], [match.span() for match in matches]


def _range_for_tokens(spans: list[tuple[int, int]], start: int, end: int) -> tuple[int, int] | None:
    if start >= end:
        return None
    return spans[start][0], spans[end - 1][1]


def build_change_preview(original: str, rewritten: str) -> ChangePreview:
    """Return non-recursive token ranges for additions, removals, and replacements."""
    old_tokens, old_spans = _tokens_with_spans(original)
    new_tokens, new_spans = _tokens_with_spans(rewritten)
    matcher = difflib.SequenceMatcher(None, old_tokens, new_tokens, autojunk=False)
    original_ranges: list[tuple[int, int]] = []
    rewritten_ranges: list[tuple[int, int]] = []
    change_groups = 0
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        change_groups += 1
        old_range = _range_for_tokens(old_spans, i1, i2)
        new_range = _range_for_tokens(new_spans, j1, j2)
        if old_range is not None:
            original_ranges.append(old_range)
        if new_range is not None:
            rewritten_ranges.append(new_range)
    return ChangePreview(tuple(original_ranges), tuple(rewritten_ranges), change_groups)
