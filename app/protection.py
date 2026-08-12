"""Exact user-selected term protection shared by every local provider."""

from __future__ import annotations

from collections.abc import Callable, Iterable
import unicodedata


MAX_PROTECTED_TERMS = 50
MAX_PROTECTED_TERM_LENGTH = 100


def normalize_protected_terms(terms: Iterable[str]) -> list[str]:
    """Validate, trim and de-duplicate short single-line exact strings."""
    normalized: list[str] = []
    for raw in terms:
        if not isinstance(raw, str):
            raise ValueError("Geschützte Begriffe müssen Text sein.")
        term = raw.strip()
        if not term:
            continue
        if len(term) > MAX_PROTECTED_TERM_LENGTH:
            raise ValueError(f"Ein geschützter Begriff darf höchstens {MAX_PROTECTED_TERM_LENGTH} Zeichen haben.")
        if any(character in "\r\n\t" or unicodedata.category(character) in {"Cc", "Cf"} for character in term):
            raise ValueError("Geschützte Begriffe dürfen keine unsichtbaren Steuer- oder Formatzeichen enthalten.")
        if term not in normalized:
            normalized.append(term)
    if len(normalized) > MAX_PROTECTED_TERMS:
        raise ValueError(f"Es können höchstens {MAX_PROTECTED_TERMS} Begriffe geschützt werden.")
    return normalized


def missing_protected_terms(text: str, terms: Iterable[str]) -> list[str]:
    """Return exact requested strings that do not occur in the source."""
    return [term for term in normalize_protected_terms(terms) if term not in text]


def _literal_spans(text: str, terms: Iterable[str]) -> list[tuple[int, int]]:
    candidates: list[tuple[int, int]] = []
    for term in normalize_protected_terms(terms):
        start = 0
        while (position := text.find(term, start)) >= 0:
            candidates.append((position, position + len(term)))
            start = position + len(term)
    candidates.sort(key=lambda span: (span[0], -span[1]))
    merged: list[tuple[int, int]] = []
    for start, end in candidates:
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def transform_outside_protected_terms(
    text: str,
    terms: Iterable[str],
    transform: Callable[[str], str],
) -> str:
    """Transform all source fragments except exact protected-term occurrences."""
    spans = _literal_spans(text, terms)
    if not spans:
        return transform(text)
    pieces: list[str] = []
    cursor = 0
    for start, end in spans:
        pieces.append(transform(text[cursor:start]))
        pieces.append(text[start:end])
        cursor = end
    pieces.append(transform(text[cursor:]))
    return "".join(pieces)
