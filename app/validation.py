from __future__ import annotations

from bisect import bisect_left
from difflib import SequenceMatcher
from functools import lru_cache
import re
import unicodedata

from .inspection import split_sentences
from .models import SemanticConstraints, ValidationWarning
from .semantic import DATE, NUMBER, URL, extract_semantics


NEGATION = re.compile(r"\b(?:not|no|never|neither|without|nicht|kein(?:e|en|em|er|es)?|nie|ohne)\b", re.I)
UNCERTAINTY = re.compile(
    r"\b(?:may|might|could|possibly|probably|perhaps|likely|appears?|suggests?|"
    r"könnte|möglicherweise|vermutlich|wohl|dürfte|eventuell|unter Umständen)\b",
    re.I,
)
CONTENT_WORD = re.compile(r"\b[^\W\d_][\wÄÖÜäöüß-]{3,}\b", re.UNICODE)
FENCED_BLOCK = re.compile(
    r"^(?P<fence>`{3,}|~{3,})[^\n]*\n[\s\S]*?^(?P=fence)[ \t]*(?=\n|$)", re.MULTILINE
)
INLINE_CODE = re.compile(r"(?<!`)`{1,2}[^\n]+?`{1,2}(?!`)")
LINK_TARGET = re.compile(r"\]\(([^)\n]+)\)")
CLAUSE_SPLIT = re.compile(
    r"(?:;|\r?\n+|\b(?:while|whereas|and|but|während|hingegen|und|aber)\b)", re.I
)
ASSOCIATION_STOPWORDS = {
    "also", "been", "being", "dem", "den", "der", "des", "die", "eine", "einer", "eines",
    "for", "from", "hat", "haben", "ist", "mit", "the", "this", "to", "von", "war", "was",
    "were", "will", "wird", "with", "zum", "zur",
}

# These deliberately small, high-confidence pairs catch a dangerous class of
# edits that exact-value checks cannot see: a model can retain every number,
# name and negation count while reversing the meaning of a nearly identical
# claim. They are not a semantic-equivalence engine. Instead they fail closed
# when an aligned EN/DE business or legal claim crosses an explicit boundary.
HIGH_RISK_POLARITY_GROUPS: tuple[tuple[str, tuple[str, ...], tuple[str, ...]], ...] = (
    (
        "permission",
        (
            "permit", "permits", "permitted", "allow", "allows", "allowed",
            "authorize", "authorizes", "authorized", "approve", "approves", "approved",
            "grant", "grants", "granted", "erlaubt", "zul\u00e4ssig", "genehmigt", "freigegeben",
        ),
        (
            "prohibit", "prohibits", "prohibited", "forbid", "forbids", "forbidden",
            "ban", "bans", "banned", "reject", "rejects", "rejected", "deny", "denies", "denied",
            "verbietet", "verboten", "untersagt", "abgelehnt", "verweigert", "unzul\u00e4ssig",
        ),
    ),
    (
        "effectiveness",
        ("effective", "valid", "enforceable", "wirksam", "g\u00fcltig"),
        ("ineffective", "invalid", "unenforceable", "unwirksam", "ung\u00fcltig"),
    ),
    (
        "direction",
        (
            "increase", "increases", "increased", "increasing", "rise", "rises", "rose", "rising",
            "grow", "grows", "grew", "growing", "higher", "steigen", "steigt", "stieg", "gestiegen",
            "erh\u00f6ht", "erh\u00f6hen", "zunehmen", "nimmt zu",
        ),
        (
            "decrease", "decreases", "decreased", "decreasing", "decline", "declines", "declined",
            "declining", "fall", "falls", "fell", "falling", "reduce", "reduces", "reduced",
            "lower", "sinken", "sinkt", "sank", "gesunken", "reduziert", "reduzieren", "abnehmen",
            "nimmt ab",
        ),
    ),
)

HIGH_RISK_MODAL_GROUPS: tuple[tuple[str, tuple[str, ...], tuple[str, ...]], ...] = (
    (
        "modal obligation",
        ("may", "might", "can", "could", "darf", "kann", "k\u00f6nnte"),
        ("must", "shall", "required to", "is required to", "muss", "m\u00fcssen", "hat zu", "verpflichtet"),
    ),
)

CLAIM_TOKEN = re.compile(r"\b[\w\u00c4\u00d6\u00dc\u00e4\u00f6\u00fc\u00df-]+\b", re.UNICODE)
HIGH_RISK_ALIGNMENT_MINIMUM = 0.55
HIGH_RISK_POSITION_WINDOW = 3
HIGH_RISK_MAX_CANDIDATES = 80


def _cleanup_artifact_equivalent(text: str) -> str:
    """Mirror only meaning-neutral Unicode cleanup for semantic comparison."""
    cleaned = unicodedata.normalize("NFC", text).replace("\r\n", "\n").replace("\r", "\n")
    if cleaned.startswith("\ufeff"):
        cleaned = cleaned[1:]
    return cleaned.replace("\u200b", "").replace("\u00ad", "").replace("\u00a0", " ").replace("\u202f", " ")


def _markdown_signature(text: str) -> dict[str, list[str] | int]:
    lines = text.splitlines()
    return {
        "fenced_code": [match.group(0) for match in FENCED_BLOCK.finditer(text)],
        "inline_code": INLINE_CODE.findall(text),
        "headings": [match.group(1) for line in lines if (match := re.match(r"^(#{1,6})\s+", line))],
        "lists": [match.group(1) for line in lines
                  if (match := re.match(r"^(\s*(?:[-*+] |\d+[.)] |[-*+] \[[ xX]\] ))", line))],
        "blockquotes": sum(bool(re.match(r"^\s*>", line)) for line in lines),
        "table_pipes": [line.count("|") for line in lines if "|" in line],
        "hard_breaks": len(re.findall(r" {2}\n", text)),
        "link_targets": LINK_TARGET.findall(text),
    }


def _content_terms(sentence: str) -> set[str]:
    return {term.casefold() for term in CONTENT_WORD.findall(sentence)}


def _value_clause_anchors(text: str, values: list[str]) -> dict[str, set[str]]:
    anchors = {value: set() for value in values}
    for clause in CLAUSE_SPLIT.split(text):
        present = [value for value in values if value in clause]
        if not present:
            continue
        context = clause
        for protected in values:
            context = context.replace(protected, " ")
        terms = _content_terms(context) - ASSOCIATION_STOPWORDS
        for value in present:
            anchors[value].update(terms)
    return anchors


def _reassigned_values(original: str, rewritten: str, values: list[str]) -> list[str]:
    """Detect strong evidence that protected values exchanged factual contexts."""
    unique_values = list(dict.fromkeys(values))
    if len(unique_values) < 2:
        return []
    original_anchors = _value_clause_anchors(original, unique_values)
    rewritten_anchors = _value_clause_anchors(rewritten, unique_values)
    reassigned = []
    for value in unique_values:
        own_context = original_anchors[value]
        new_context = rewritten_anchors[value]
        if len(own_context) < 2 or len(new_context) < 2:
            continue
        own_score = len(own_context & new_context)
        other_score = max(
            (len(original_anchors[other] & new_context) for other in unique_values if other != value),
            default=0,
        )
        if other_score >= 2 and other_score > own_score:
            reassigned.append(value)
    return reassigned


@lru_cache(maxsize=None)
def _marker_pattern(markers: tuple[str, ...]) -> re.Pattern[str]:
    """Compile each small marker group once, including whitespace-tolerant phrases."""
    fragments = [
        re.escape(marker).replace(r"\ ", r"\s+")
        for marker in sorted(markers, key=len, reverse=True)
    ]
    return re.compile(rf"(?<![\w-])(?:{'|'.join(fragments)})(?![\w-])", re.I)


def _marker_matches(sentence: str, markers: tuple[str, ...]) -> tuple[str, ...]:
    """Return explicit high-risk markers without matching inside larger words."""
    return tuple(match.group(0).casefold() for match in _marker_pattern(markers).finditer(sentence))


def _marker_side(
    sentence: str,
    left_markers: tuple[str, ...],
    right_markers: tuple[str, ...],
) -> tuple[str | None, tuple[str, ...], tuple[str, ...]]:
    """Classify one unambiguous side of a paired high-risk marker group."""
    left = _marker_matches(sentence, left_markers)
    right = _marker_matches(sentence, right_markers)
    if bool(left) == bool(right):
        return None, left, right
    return ("left" if left else "right"), left, right


def _claim_tokens(sentence: str) -> tuple[str, ...]:
    return tuple(token.casefold() for token in CLAIM_TOKEN.findall(sentence))


def _alignment_terms(tokens: tuple[str, ...]) -> set[str]:
    """Use substantive shared words to avoid pairing unrelated nearby sentences."""
    ignored = ASSOCIATION_STOPWORDS | {
        "about", "after", "also", "and", "are", "before", "but", "das", "dass", "der", "die",
        "ein", "eine", "einer", "einem", "einen", "es", "for", "from", "has", "have", "here",
        "into", "its", "more", "not", "oder", "sein", "sie", "that", "the", "their", "this",
        "und", "was", "wer", "wie", "with", "wurde", "werden", "which", "will", "wird",
    }
    return {term for term in tokens if len(term) >= 4 and term not in ignored}


def _candidate_index(sentences: list[str]) -> dict[str, list[int]]:
    index: dict[str, list[int]] = {}
    for position, sentence in enumerate(sentences):
        for term in _alignment_terms(_claim_tokens(sentence)):
            index.setdefault(term, []).append(position)
    return index


def _nearest_positions(positions: list[int], target: int, maximum: int) -> list[int]:
    """Return a small proximity window from an already sorted inverted index."""
    cursor = bisect_left(positions, target)
    left, right = cursor - 1, cursor
    selected: list[int] = []
    while len(selected) < maximum and (left >= 0 or right < len(positions)):
        left_distance = abs(positions[left] - target) if left >= 0 else float("inf")
        right_distance = abs(positions[right] - target) if right < len(positions) else float("inf")
        if left_distance <= right_distance:
            selected.append(positions[left])
            left -= 1
        else:
            selected.append(positions[right])
            right += 1
    return selected


def _best_aligned_claim(
    source_position: int,
    source_sentence: str,
    candidates: list[str],
    index: dict[str, list[int]] | None = None,
) -> tuple[int, str] | None:
    """Find a plausibly corresponding rewritten claim without quadratic scans."""
    if source_position < len(candidates) and source_sentence == candidates[source_position]:
        return source_position, candidates[source_position]
    source_tokens = _claim_tokens(source_sentence)
    positions = set(range(
        max(0, source_position - HIGH_RISK_POSITION_WINDOW),
        min(len(candidates), source_position + HIGH_RISK_POSITION_WINDOW + 1),
    ))

    def score_positions(candidate_positions: set[int]) -> tuple[float, int] | None:
        scored = []
        for position in candidate_positions:
            candidate_tokens = _claim_tokens(candidates[position])
            score = SequenceMatcher(None, source_tokens, candidate_tokens, autojunk=False).ratio()
            scored.append((score, -abs(position - source_position), position))
        if not scored:
            return None
        score, _distance, position = max(scored)
        return score, position

    local = score_positions(positions)
    # Sentence order usually survives an editorial rewrite. A credible nearby
    # counterpart is enough; expanding a high-frequency index for it turns
    # repeated business templates into a quadratic workload.
    if local is not None and local[0] >= HIGH_RISK_ALIGNMENT_MINIMUM:
        return local[1], candidates[local[1]]

    if index is None:
        return None

    for term in sorted(_alignment_terms(source_tokens)):
        for position in _nearest_positions(index.get(term, []), source_position, 8):
            positions.add(position)
            if len(positions) >= HIGH_RISK_MAX_CANDIDATES:
                break
        if len(positions) >= HIGH_RISK_MAX_CANDIDATES:
            break
    best = score_positions(positions)
    if best is None or best[0] < HIGH_RISK_ALIGNMENT_MINIMUM:
        return None
    position = best[1]
    return position, candidates[position]


def _high_risk_claim_warnings(original: str, rewritten: str) -> list[ValidationWarning]:
    """Fail closed for high-risk polarity, direction, and modal inversions.

    The comparison is intentionally limited to closely aligned claims. This avoids
    treating independent mentions of, for example, an approval and a rejection in
    different sentences as a semantic reversal.
    """
    if original == rewritten or _cleanup_artifact_equivalent(original) == rewritten:
        return []
    source_claims = split_sentences(original)
    rewritten_claims = split_sentences(rewritten)
    if not source_claims or not rewritten_claims:
        return []
    warnings: list[ValidationWarning] = []
    candidate_terms: dict[str, list[int]] | None = None
    groups = (
        *(("changed_claim_polarity",) + group for group in HIGH_RISK_POLARITY_GROUPS),
        *(("changed_modal_obligation",) + group for group in HIGH_RISK_MODAL_GROUPS),
    )
    for warning_kind, group_name, left_markers, right_markers in groups:
        for source_position, source_claim in enumerate(source_claims):
            source_side, source_left, source_right = _marker_side(source_claim, left_markers, right_markers)
            if source_side is None:
                continue
            aligned = _best_aligned_claim(source_position, source_claim, rewritten_claims)
            if aligned is None:
                if candidate_terms is None:
                    candidate_terms = _candidate_index(rewritten_claims)
                aligned = _best_aligned_claim(
                    source_position,
                    source_claim,
                    rewritten_claims,
                    candidate_terms,
                )
            if aligned is None:
                continue
            _rewritten_position, rewritten_claim = aligned
            rewritten_side, rewritten_left, rewritten_right = _marker_side(
                rewritten_claim, left_markers, right_markers
            )
            if rewritten_side == source_side:
                continue
            before_markers = source_left or source_right
            after_markers = rewritten_left or rewritten_right
            before_label = "/".join(before_markers)
            after_label = "/".join(after_markers) if after_markers else "removed"
            warnings.append(ValidationWarning(
                kind=warning_kind,
                severity="high",
                value=f"{group_name}: {before_label} -> {after_label}",
                message=(
                    "A high-risk polarity, direction, or modal statement changed in a closely aligned claim. "
                    "The candidate must be reviewed or rejected."
                ),
            ))
            # One confirmed high-severity inversion rejects the candidate. It is
            # sufficient for a safe fallback and keeps both the audit and the UI
            # bounded for documents containing repeated template sentences.
            return warnings
    return warnings


def validate_preservation(original: str, rewritten: str, constraints: SemanticConstraints,
                          *, preserve_numbers: bool = True, preserve_citations: bool = True,
                          preserve_quotations: bool = True) -> list[ValidationWarning]:
    warnings: list[ValidationWarning] = []
    checks = (("number", constraints.numbers if preserve_numbers else []),
              ("date", constraints.dates if preserve_numbers else []),
              ("proper_name", constraints.names),
              ("citation", constraints.citations if preserve_citations else []),
              ("quotation", constraints.quotations if preserve_quotations else []),
              ("protected_term", constraints.protected_terms))
    for kind, values in checks:
        for value in values:
            if value not in rewritten:
                warnings.append(ValidationWarning(kind=f"missing_{kind}", severity="high", value=value,
                    message=f"Original {kind.replace('_', ' ')} is absent or changed in the rewrite."))
            elif kind in {
                "number", "date", "proper_name", "citation", "quotation", "protected_term"
            } and original.count(value) != rewritten.count(value):
                warnings.append(ValidationWarning(
                    kind=f"altered_{kind}_count",
                    severity="high",
                    value=value,
                    message=f"The number of occurrences of this {kind.replace('_', ' ')} changed.",
                ))
    if preserve_citations:
        for citation in constraints.citations:
            original_angle = f"<{citation}>" in original
            rewritten_angle = f"<{citation}>" in rewritten
            original_markdown = bool(re.search(rf"\]\({re.escape(citation)}\)", original))
            rewritten_markdown = bool(re.search(rf"\]\({re.escape(citation)}\)", rewritten))
            if (original_angle, original_markdown) != (rewritten_angle, rewritten_markdown):
                warnings.append(ValidationWarning(kind="altered_citation_format", severity="high",
                    value=citation, message="Citation or URL embedding changed in the rewrite."))
    new_semantics = extract_semantics(rewritten)
    artifact_equivalent_original = _cleanup_artifact_equivalent(original)
    for kind, values, originals in (
        ("number", new_semantics.numbers if preserve_numbers else [], constraints.numbers),
        ("date", new_semantics.dates if preserve_numbers else [], constraints.dates),
        ("proper_name", new_semantics.names, constraints.names),
        ("citation", new_semantics.citations if preserve_citations else [], constraints.citations),
        ("quotation", new_semantics.quotations if preserve_quotations else [], constraints.quotations),
    ):
        for value in values:
            if value not in originals and value not in artifact_equivalent_original:
                warnings.append(ValidationWarning(kind=f"new_{kind}", severity="high", value=value,
                    message=f"Rewrite introduces a {kind} not found in the original."))
    original_terms = set(re.findall(r"\b[\wÄÖÜäöüß-]{5,}\b", original.casefold()))
    for sentence in new_semantics.core_claims:
        terms = set(re.findall(r"\b[\wÄÖÜäöüß-]{5,}\b", sentence.casefold()))
        if len(terms) >= 4 and len(terms & original_terms) / len(terms) <= .35:
            warnings.append(ValidationWarning(kind="unsupported_new_claim", severity="medium", value=sentence,
                message="Sentence has low lexical support in the original; review its factual basis."))

    original_markdown = _markdown_signature(original)
    rewritten_markdown = _markdown_signature(rewritten)
    for feature, original_value in original_markdown.items():
        if original_value != rewritten_markdown[feature]:
            warnings.append(ValidationWarning(
                kind="altered_markdown_structure",
                severity="high",
                value=feature,
                message=f"Markdown {feature.replace('_', ' ')} changed in the rewrite.",
            ))

    if len(NEGATION.findall(original)) != len(NEGATION.findall(rewritten)):
        warnings.append(ValidationWarning(
            kind="altered_negation", severity="high", value="negation",
            message="The number of explicit negations changed in the rewrite.",
        ))
    if len(UNCERTAINTY.findall(original)) != len(UNCERTAINTY.findall(rewritten)):
        warnings.append(ValidationWarning(
            kind="altered_uncertainty", severity="high", value="uncertainty",
            message="The number of explicit uncertainty markers changed in the rewrite.",
        ))

    warnings.extend(_high_risk_claim_warnings(original, rewritten))

    association_groups = [
        ("numeric", constraints.numbers if preserve_numbers else []),
        ("date", constraints.dates if preserve_numbers else []),
        ("proper_name", constraints.names),
        ("citation", constraints.citations if preserve_citations else []),
        ("quotation", constraints.quotations if preserve_quotations else []),
        ("protected_term", constraints.protected_terms),
    ]
    for kind, values in association_groups:
        for value in _reassigned_values(original, rewritten, values):
            warnings.append(ValidationWarning(
                kind=f"reassigned_{kind}_context",
                severity="high",
                value=value,
                message=f"A preserved {kind.replace('_', ' ')} appears to have moved to another factual context.",
            ))

    rewritten_claim_terms = [_content_terms(sentence) for sentence in new_semantics.core_claims]
    for claim in constraints.core_claims:
        terms = _content_terms(claim)
        if len(terms) < 4:
            continue
        best_recall = max((len(terms & candidate) / len(terms) for candidate in rewritten_claim_terms), default=0.0)
        if best_recall < 0.30:
            warnings.append(ValidationWarning(
                kind="missing_or_reassigned_claim",
                severity="high",
                value=claim,
                message="An original claim has insufficient lexical support in the rewrite.",
            ))
    return warnings
