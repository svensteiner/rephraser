from __future__ import annotations

import difflib
import re

from .inspection import split_sentences
from .models import DiffReport


def create_diff(original: str, rewritten: str) -> DiffReport:
    old_words, new_words = re.findall(r"\S+\s*", original), re.findall(r"\S+\s*", rewritten)
    old_tokens = [token.casefold() for token in re.findall(r"\b\w+\b", original)]
    new_tokens = [token.casefold() for token in re.findall(r"\b\w+\b", rewritten)]
    lexical_similarity = difflib.SequenceMatcher(None, old_tokens, new_tokens).ratio()
    old_sentences, new_sentences = split_sentences(original), split_sentences(rewritten)
    word_diff = list(difflib.ndiff(old_words, new_words))
    sentence_diff = list(difflib.ndiff(old_sentences, new_sentences))
    matcher = difflib.SequenceMatcher(None, old_sentences, new_sentences)
    added, removed, rewritten_items = [], [], []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "insert": added.extend(new_sentences[j1:j2])
        elif tag == "delete": removed.extend(old_sentences[i1:i2])
        elif tag == "replace":
            old, new = old_sentences[i1:i2], new_sentences[j1:j2]
            for left, right in zip(old, new):
                similarity = difflib.SequenceMatcher(None, left, right).ratio()
                rewritten_items.append({"original": left, "rewritten": right, "similarity": round(similarity, 3)})
            if len(old) > len(new): removed.extend(old[len(new):])
            if len(new) > len(old): added.extend(new[len(old):])
    return DiffReport(word_diff=word_diff, sentence_diff=sentence_diff,
        lexical_similarity=round(lexical_similarity, 3),
        surface_diversity=round(1.0 - lexical_similarity, 3),
        added_sentences=added, removed_sentences=removed,
        substantially_rewritten_sentences=[item for item in rewritten_items if item["similarity"] < .7])
