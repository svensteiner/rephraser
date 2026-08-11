from __future__ import annotations

import re

from .inspection import split_sentences
from .models import SemanticConstraints

URL = r"https?://[^\s<>\])}\"”’»]+"
NUMBER = r"(?<![\w\d])(?:(?:EUR|USD|CHF|€)\s*)?[-+]?(?:\d{1,3}(?:[. ,]\d{3})+|\d+)(?:[,.]\d+)?\s*(?:(?:Mio\.|Mrd\.)\s*)?(?:%|EUR|USD|CHF|€|BTC|ETH|USDT)?(?![\w\d])"
MONTHS = r"Januar|Februar|März|April|Mai|Juni|Juli|August|September|Oktober|November|Dezember|January|February|March|April|May|June|July|August|September|October|November|December"
DATE = rf"\b(?:\d{{1,2}}[./-]\d{{1,2}}[./-]\d{{2,4}}|\d{{4}}-\d{{2}}-\d{{2}}|(?:den\s+)?\d{{1,2}}\.?(?:\s+)(?:{MONTHS})\s+\d{{4}}|(?:{MONTHS})\s+\d{{1,2}},?\s+\d{{4}})\b"
QUOTE = r"(?:\"[^\"\n]+\"|„[^“\n]+“|“[^”\n]+”|»[^«\n]+«|«[^»\n]+»|‘[^’\n]+’)"


def _unique(matches: list[str]) -> list[str]:
    return list(dict.fromkeys(item.strip() for item in matches if item.strip()))


def extract_semantics(text: str) -> SemanticConstraints:
    sentences = split_sentences(text)
    citations = _unique([item.rstrip(".,;:") for item in re.findall(URL, text)])
    quotes = _unique(re.findall(QUOTE, text))
    dates = _unique(re.findall(DATE, text, re.I))
    numbers = _unique(re.findall(NUMBER, text))
    names = _unique(re.findall(
        r"(?<![#@])\b(?:[A-ZÄÖÜ][\wÄÖÜäöüß-]+\s+){1,3}[A-ZÄÖÜ][\wÄÖÜäöüß-]+\b|\b[A-Z]{2,8}\b",
        text,
    ))
    uncertain = [s for s in sentences if re.search(r"\b(?:may|might|could|possibly|probably|perhaps|könnte|möglicherweise|vermutlich|wohl)\b", s, re.I)]
    facts = [s for s in sentences if re.search(NUMBER + "|" + DATE + "|" + URL, s, re.I)]
    claims = [s for s in sentences if s not in uncertain][:10]
    structure = [re.sub(r"^#{1,6}\s*", "", line).strip() for line in text.splitlines()
                 if re.match(r"^#{1,6}\s+", line)] or [f"Paragraph {i + 1}" for i, p in enumerate(re.split(r"\n\s*\n", text)) if p.strip()]
    must = _unique(numbers + dates + quotes + citations + names)
    return SemanticConstraints(core_claims=claims, facts=facts, numbers=numbers, names=names,
        dates=dates, quotations=quotes, citations=citations, argument_structure=structure,
        uncertainties=uncertain, must_preserve=must)
