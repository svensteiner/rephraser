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


@dataclass(frozen=True, slots=True)
class ChangeSegment:
    original_start: int
    original_end: int
    rewritten_start: int
    rewritten_end: int
    before: str
    after: str


def _tokens_with_spans(text: str) -> tuple[list[str], list[tuple[int, int]]]:
    matches = list(TOKEN.finditer(text))
    return [match.group() for match in matches], [match.span() for match in matches]


def _range_for_tokens(spans: list[tuple[int, int]], start: int, end: int) -> tuple[int, int] | None:
    if start >= end:
        return None
    return spans[start][0], spans[end - 1][1]


def _boundary(spans: list[tuple[int, int]], index: int, text_length: int) -> int:
    return spans[index][0] if index < len(spans) else text_length


def build_change_segments(original: str, rewritten: str) -> tuple[ChangeSegment, ...]:
    """Return ordered, exact changes that can be independently accepted or rejected."""
    old_tokens, old_spans = _tokens_with_spans(original)
    new_tokens, new_spans = _tokens_with_spans(rewritten)
    matcher = difflib.SequenceMatcher(None, old_tokens, new_tokens, autojunk=False)
    segments: list[ChangeSegment] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        old_start = _boundary(old_spans, i1, len(original))
        old_end = old_spans[i2 - 1][1] if i2 > i1 else old_start
        new_start = _boundary(new_spans, j1, len(rewritten))
        new_end = new_spans[j2 - 1][1] if j2 > j1 else new_start
        segments.append(ChangeSegment(
            original_start=old_start,
            original_end=old_end,
            rewritten_start=new_start,
            rewritten_end=new_end,
            before=original[old_start:old_end],
            after=rewritten[new_start:new_end],
        ))
    return tuple(segments)


def apply_change_selection(
    original: str,
    segments: tuple[ChangeSegment, ...],
    selected: tuple[bool, ...],
) -> str:
    """Rebuild a document from the original and independently selected changes."""
    if len(segments) != len(selected):
        raise ValueError("Selection count must match change segment count.")
    pieces: list[str] = []
    cursor = 0
    for segment, accepted in zip(segments, selected, strict=True):
        if segment.original_start < cursor or segment.original_end < segment.original_start:
            raise ValueError("Change segments must be ordered and non-overlapping.")
        pieces.append(original[cursor:segment.original_start])
        pieces.append(segment.after if accepted else segment.before)
        cursor = segment.original_end
    pieces.append(original[cursor:])
    return "".join(pieces)


def build_change_preview(original: str, rewritten: str) -> ChangePreview:
    """Return non-recursive token ranges for additions, removals, and replacements."""
    segments = build_change_segments(original, rewritten)
    return ChangePreview(
        tuple((item.original_start, item.original_end) for item in segments if item.before),
        tuple((item.rewritten_start, item.rewritten_end) for item in segments if item.after),
        len(segments),
    )
