from __future__ import annotations

from collections import Counter
import math
import re
import statistics

from .inspection import TRANSITIONS, split_sentences
from .models import QualityMetrics

FILLERS = TRANSITIONS + ("it is important to note", "in today's world", "needless to say",
                         "es ist wichtig zu beachten", "in der heutigen zeit", "grundsätzlich")


def calculate_metrics(text: str) -> QualityMetrics:
    sentences = split_sentences(text)
    lengths = [len(re.findall(r"\b[\w'-]+\b", s)) for s in sentences]
    words = re.findall(r"\b[^\W\d_][\w'-]*\b", text.casefold())
    counts = Counter(words)
    paragraphs = [p for p in re.split(r"\n\s*\n", text) if p.strip()]
    syllable_proxy = sum(max(1, len(re.findall(r"[aeiouyäöü]+", w, re.I))) for w in words)
    readability = 180 - (len(words) / max(1, len(sentences))) - 58.5 * (syllable_proxy / max(1, len(words)))
    passive = len(re.findall(r"\b(?:wird|wurde|werden|wurden|is|are|was|were|be|been)\b\s+\w+(?:ed|en|t)\b", text, re.I))
    return QualityMetrics(sentence_count=len(sentences), sentence_length_min=min(lengths, default=0),
        sentence_length_max=max(lengths, default=0), sentence_length_mean=round(statistics.mean(lengths), 2) if lengths else 0,
        sentence_length_stdev=round(statistics.pstdev(lengths), 2) if lengths else 0,
        paragraph_lengths=[len(re.findall(r"\S+", p)) for p in paragraphs],
        lexical_diversity=round(len(set(words)) / max(1, len(words)), 3),
        repeated_word_count=sum(v - 1 for v in counts.values() if v > 1),
        filler_phrase_count=sum(len(re.findall(re.escape(p), text, re.I)) for p in FILLERS),
        passive_voice_indicators=passive, readability=round(readability, 2))
