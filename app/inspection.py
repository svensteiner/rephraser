from __future__ import annotations

from collections import Counter
import re
import unicodedata

from .models import CharacterFinding, CharacterSummary, InspectionReport

KNOWN = {"\u200b": "zero_width", "\u200c": "zero_width", "\u200d": "zero_width",
         "\ufeff": "BOM", "\u00ad": "soft_hyphen", "\u00a0": "non_breaking_space",
         "\u202f": "non_breaking_space"}
TRANSITIONS = ("however", "moreover", "furthermore", "therefore", "in conclusion",
               "allerdings", "darüber hinaus", "zudem", "daher", "abschließend")
MONTH_NAMES = ("Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August",
               "September", "Oktober", "November", "Dezember", "January", "February",
               "March", "April", "May", "June", "July", "August", "September", "October",
               "November", "December")


def split_sentences(text: str) -> list[str]:
    marker = "\ue000"
    protected = re.sub(
        rf"\b(\d{{1,2}})\.\s+(?=({'|'.join(MONTH_NAMES)})\b)",
        rf"\1{marker} ",
        text,
        flags=re.I,
    )
    protected = re.sub(
        r"\b(z\.\s*B|u\.\s*a|d\.\s*h|Dr|Prof|Mio|Mrd)\.",
        lambda match: match.group(0).replace(".", marker),
        protected,
        flags=re.I,
    )
    parts = re.split(r"(?<=[.!?])\s+|(?<=[.!?][\"”’»])\s+|\n+(?=\S)", protected)
    return [part.replace(marker, ".").strip() for part in parts if part.strip()]


def inspect_text(text: str) -> InspectionReport:
    findings = []
    for pos, char in enumerate(text):
        category = unicodedata.category(char)
        kind = KNOWN.get(char)
        if kind is None and char.isspace() and char not in " \t\r\n":
            kind = "unusual_whitespace"
        if kind is None and category == "Cf":
            kind = "unknown_format_character"
        if kind is None and category.startswith("C") and char not in "\t\r\n":
            kind = "control_character"
        if kind:
            findings.append(CharacterFinding(position=pos, code_point=f"U+{ord(char):04X}",
                name=unicodedata.name(char, "<unnamed>"), category=category, kind=kind))
    grouped: dict[tuple[str, str, str, str], list[int]] = {}
    for finding in findings:
        key = (finding.code_point, finding.name, finding.category, finding.kind)
        grouped.setdefault(key, []).append(finding.position)
    summary = [
        CharacterSummary(
            code_point=code_point,
            name=name,
            category=category,
            kind=kind,
            count=len(positions),
            positions=positions,
        )
        for (code_point, name, category, kind), positions in grouped.items()
    ]
    sentences = split_sentences(text)
    lengths = [len(re.findall(r"\b[\w'-]+\b", sentence)) for sentence in sentences]
    words = [w.casefold() for w in re.findall(r"\b[^\W\d_][\w'-]*\b", text)]
    word_counts = Counter(w for w in words if len(w) > 3)
    bigrams = Counter(" ".join(words[i:i + 2]) for i in range(len(words) - 1))
    repetitions = dict(bigrams.most_common(10))
    repetitions = {key: value for key, value in repetitions.items() if value > 1}
    transitions = {phrase: len(re.findall(rf"\b{re.escape(phrase)}\b", text, re.I))
                   for phrase in TRANSITIONS}
    transitions = {key: value for key, value in transitions.items() if value}
    uniform = len(lengths) >= 4 and (max(lengths) - min(lengths) <= 5)
    headings = [line.strip() for line in text.splitlines()
                if re.match(r"^#{1,6}\s+", line) or re.match(r"^[A-ZÄÖÜ][^.!?]{1,60}:$", line)]
    list_items = sum(bool(re.match(r"^\s*(?:[-*+] |\d+[.)] )", line)) for line in text.splitlines())
    paragraphs = len([p for p in re.split(r"\r?\n\s*\r?\n", text) if p.strip()])
    return InspectionReport(characters=findings, character_summary=summary,
        paragraphs=paragraphs, sentences=len(sentences),
        sentence_lengths=lengths, repeated_phrases=repetitions,
        lexical_repetition={k: v for k, v in word_counts.most_common(10) if v > 2},
        transition_phrases=transitions, uniform_sentence_pattern=uniform,
        headings=headings, list_items=list_items)
