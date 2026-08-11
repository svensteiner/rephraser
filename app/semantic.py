from __future__ import annotations

import re

from .inspection import split_sentences
from .models import SemanticConstraints

URL = r"https?://[^\s<>\])}\"”’»]+"
NUMBER = r"(?<![\w\d])(?:(?:EUR|USD|CHF|€)\s*)?[-+]?(?:\d{1,3}(?:[. ,]\d{3})+|\d+)(?:[,.]\d+)?\s*(?:(?:Mio\.|Mrd\.)\s*)?(?:%|EUR|USD|CHF|€|BTC|ETH|USDT)?(?![\w\d])"
MONTHS = r"Januar|Februar|März|April|Mai|Juni|Juli|August|September|Oktober|November|Dezember|January|February|March|April|May|June|July|August|September|October|November|December"
DATE = rf"\b(?:\d{{1,2}}[./-]\d{{1,2}}[./-]\d{{2,4}}|\d{{4}}-\d{{2}}-\d{{2}}|(?:den\s+)?\d{{1,2}}\.?(?:\s+)(?:{MONTHS})\s+\d{{4}}|(?:{MONTHS})\s+\d{{1,2}},?\s+\d{{4}})\b"
QUOTE = r"(?:\"[^\"\n]+\"|„[^“\n]+“|“[^”\n]+”|»[^«\n]+«|«[^»\n]+»|‘[^’\n]+’)"

NAME = re.compile(
    r"(?<![#@])\b[A-ZÄÖÜ][\wÄÖÜäöüß-]+(?:[ \t]+[A-ZÄÖÜ][\wÄÖÜäöüß-]+){1,3}\b"
)
ACRONYM = re.compile(r"(?<![#@\w])\b[A-ZÄÖÜ]{2,8}\b")
NON_NAME_STARTERS = {
    "am", "an", "auf", "aus", "bei", "das", "dem", "den", "der", "des", "die", "ein", "eine",
    "für", "im", "in", "mit", "ohne", "seit", "über", "um", "vom", "von", "vor", "wir", "zum", "zur",
    "a", "an", "at", "could", "dear", "for", "from", "hello", "hi", "in", "on", "please", "regarding",
    "thank", "that", "the", "these", "this", "those", "to", "we", "with", "without", "would", "you",
}


def _unique(matches: list[str]) -> list[str]:
    return list(dict.fromkeys(item.strip() for item in matches if item.strip()))


def _mask_matches(text: str, pattern: str, flags: int = 0) -> str:
    """Replace matched characters with spaces while preserving line topology."""
    characters = list(text)
    for match in re.finditer(pattern, text, flags):
        for position in range(match.start(), match.end()):
            if characters[position] not in "\r\n":
                characters[position] = " "
    return "".join(characters)


def _extract_names(text: str) -> list[str]:
    candidates = []
    for match in NAME.finditer(text):
        candidate = match.group(0)
        if candidate.split()[0].casefold() not in NON_NAME_STARTERS:
            candidates.append(candidate)
    candidates.extend(match.group(0) for match in ACRONYM.finditer(text))
    return _unique(candidates)


def extract_semantics(text: str) -> SemanticConstraints:
    sentences = split_sentences(text)
    citations = _unique([item.rstrip(".,;:") for item in re.findall(URL, text)])
    quotes = _unique(re.findall(QUOTE, text))
    dates = _unique(re.findall(DATE, text, re.I))
    numbers = _unique(re.findall(NUMBER, _mask_matches(text, DATE, re.I)))
    names = _extract_names(text)
    uncertain = [s for s in sentences if re.search(
        r"\b(?:may|might|could|possibly|probably|perhaps|likely|appears?|suggests?|"
        r"könnte|möglicherweise|vermutlich|wohl|dürfte|eventuell|unter Umständen)\b",
        s,
        re.I,
    )]
    facts = [s for s in sentences if re.search(NUMBER + "|" + DATE + "|" + URL, s, re.I)]
    claims = [s for s in sentences if s not in uncertain]
    structure = [re.sub(r"^#{1,6}\s*", "", line).strip() for line in text.splitlines()
                 if re.match(r"^#{1,6}\s+", line)] or [f"Paragraph {i + 1}" for i, p in enumerate(re.split(r"\n\s*\n", text)) if p.strip()]
    must = _unique(numbers + dates + quotes + citations + names)
    return SemanticConstraints(core_claims=claims, facts=facts, numbers=numbers, names=names,
        dates=dates, quotations=quotes, citations=citations, argument_structure=structure,
        uncertainties=uncertain, must_preserve=must)
