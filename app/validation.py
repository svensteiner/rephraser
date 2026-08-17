from __future__ import annotations

from bisect import bisect_left
from difflib import SequenceMatcher
from functools import lru_cache
import re
import unicodedata

from .inspection import split_sentences
from .models import SemanticConstraints, ValidationWarning
from .semantic import (
    DATE,
    NUMBER,
    URL,
    extract_monetary_amounts,
    extract_numeric_table_layouts,
    extract_payment_obligations,
    extract_reporting_periods,
    extract_semantics,
)


# ``cannot`` is deliberately separate from ``can``: it is one lexical token,
# while ``can not`` is two.  Treating both as an explicit negation lets the
# preservation check catch a model that silently moves a prohibition to a
# different claim while retaining the same number of ordinary "not" tokens.
NEGATION = re.compile(
    r"(?:\b(?:cannot|can\s+not|not|no|never|neither|without|"
    r"nicht|kein(?:e|en|em|er|es)?|nie|ohne)\b|\b(?:can['’]t|won['’]t|"
    r"isn['’]t|aren['’]t|doesn['’]t|don['’]t|didn['’]t)\b)",
    re.I,
)
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

# Threshold language is materially directional even when its numeric value is
# unchanged.  The lists intentionally stay small and explicit: this is a
# fail-closed guard for clear comparator inversions, not a parser for every
# quantitative expression.
HIGH_RISK_COMPARATOR_GROUPS: tuple[tuple[str, tuple[str, ...], tuple[str, ...]], ...] = (
    (
        "threshold",
        (
            "at least", "not less than", "no fewer than", "minimum",
            "mindestens", "zumindest", "nicht weniger als",
        ),
        (
            "at most", "not more than", "no more than", "maximum",
            "h\u00f6chstens", "maximal", "nicht mehr als",
        ),
    ),
)

# Short status statements often have too few content words for the general
# claim-recall heuristic.  These pairs cover clear operational, availability,
# completion, and case-status reversals without trying to infer every possible
# status synonym.
HIGH_RISK_STATUS_GROUPS: tuple[tuple[str, tuple[str, ...], tuple[str, ...]], ...] = (
    (
        "approval status",
        ("approved", "approve", "genehmigt", "freigegeben"),
        ("rejected", "reject", "abgelehnt", "verworfen", "zur\u00fcckgewiesen"),
    ),
    (
        "validity status",
        ("valid", "enforceable", "g\u00fcltig", "wirksam"),
        ("invalid", "unenforceable", "ung\u00fcltig", "unwirksam"),
    ),
    (
        "activity status",
        ("active", "aktiv"),
        ("inactive", "inaktiv"),
    ),
    (
        "availability status",
        ("available", "verf\u00fcgbar"),
        ("unavailable", "not available", "nicht verf\u00fcgbar"),
    ),
    (
        "case status",
        ("open", "pending", "offen", "anh\u00e4ngig", "ausstehend"),
        ("closed", "resolved", "geschlossen", "erledigt", "abgeschlossen"),
    ),
    (
        "completion status",
        ("complete", "vollst\u00e4ndig"),
        ("incomplete", "unvollst\u00e4ndig"),
    ),
    (
        "payment status",
        ("paid", "bezahlt"),
        ("unpaid", "unbezahlt"),
    ),
    (
        "confirmation status",
        ("confirmed", "best\u00e4tigt"),
        ("unconfirmed", "not confirmed", "unbest\u00e4tigt", "nicht best\u00e4tigt"),
    ),
)

CLAIM_TOKEN = re.compile(r"\b[\w\u00c4\u00d6\u00dc\u00e4\u00f6\u00fc\u00df-]+\b", re.UNICODE)
HIGH_RISK_ALIGNMENT_MINIMUM = 0.55
HIGH_RISK_POSITION_WINDOW = 3
HIGH_RISK_MAX_CANDIDATES = 80
# Bound both SequenceMatcher input and the number of high-risk comparisons.
# If a non-identical candidate exceeds this safety budget, callers receive a
# high-severity warning and the pipeline returns its safe fallback instead of
# silently skipping the semantic check.
HIGH_RISK_MAX_TOKENS_PER_CLAIM = 240
HIGH_RISK_MAX_RISK_CLAIMS = 2_000
MATERIAL_CLAUSE_SPLIT = re.compile(
    r"\s*(?:;|\b(?:but|whereas|however|yet|aber|jedoch|hingegen|w\u00e4hrend)\b)\s*",
    re.I,
)
STATE_SCOPE_IGNORED = {
    "can", "cannot", "could", "darf", "kann", "konnte", "k\u00f6nnte", "may", "might",
    "must", "nicht", "no", "not", "never", "neither", "without", "ohne", "nie",
}


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
    matches = []
    for match in _marker_pattern(markers).finditer(sentence):
        marker = match.group(0).casefold()
        # ``can not`` / ``can't`` and ``kann nicht`` are explicit negative
        # capability statements, not the positive modal ``can`` / ``kann``.
        # Keeping them out of the positive-modal group prevents a spelling-only
        # normalization (``cannot`` <-> ``can not``) from looking like a new
        # permission or obligation.
        if marker in {"can", "kann"} and re.match(
            r"(?:\s+(?:not|nicht)\b|['\u2019]t\b)", sentence[match.end():], re.I
        ):
            continue
        matches.append(marker)
    return tuple(matches)


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
    tokens = tuple(token.casefold() for token in CLAIM_TOKEN.findall(sentence))
    if len(tokens) <= HIGH_RISK_MAX_TOKENS_PER_CLAIM:
        return tokens
    # Alignment only establishes a likely counterpart; marker detection still
    # inspects the complete sentence. Keeping both ends is resilient to normal
    # editorial additions while placing a hard cap on SequenceMatcher work.
    edge = HIGH_RISK_MAX_TOKENS_PER_CLAIM // 2
    return tokens[:edge] + tokens[-edge:]


def _material_units(claims: list[str]) -> list[str]:
    """Split only clear contrastive clauses for state-association checks.

    We intentionally do not split every ``and``/``und``: doing so turns normal
    noun phrases into pseudo-claims and makes a fail-closed guard needlessly
    noisy. Semicolons and contrastive conjunctions are enough to catch the
    common "A cannot … but B can …" relocation pattern.
    """
    return [
        unit.strip()
        for claim in claims
        for unit in MATERIAL_CLAUSE_SPLIT.split(claim)
        if unit.strip()
    ]


def _state_scope_terms(unit: str) -> set[str]:
    """Return lexical anchors for associating an explicit state with a claim."""
    return _alignment_terms(_claim_tokens(unit)) - STATE_SCOPE_IGNORED


def _high_risk_scan_limit_warning() -> ValidationWarning:
    return ValidationWarning(
        kind="high_risk_claim_scan_limit",
        severity="high",
        value=f"more than {HIGH_RISK_MAX_RISK_CLAIMS:,} high-risk claims",
        message=(
            "The candidate contains too many high-risk claims for a bounded local semantic check. "
            "It must be reviewed or rejected instead of being silently accepted."
        ),
    )


def _scope_similarity(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / max(len(left), len(right))


def _moved_state_warning(
    source_units: list[str],
    rewritten_units: list[str],
    *,
    pattern: re.Pattern[str],
    original_marker_count: int,
    rewritten_marker_count: int,
    warning_kind: str,
    label: str,
) -> ValidationWarning | None:
    """Detect a same-count explicit state moved to another material claim.

    Count checks already cover a removed ``not`` or ``may``. This additional
    association check is deliberately activated only when the counts agree and
    are non-zero, which is the dangerous relocation case the count check misses.
    """
    if original_marker_count == 0 or original_marker_count != rewritten_marker_count:
        return None
    if original_marker_count > HIGH_RISK_MAX_RISK_CLAIMS:
        return _high_risk_scan_limit_warning()

    candidate_index: dict[str, list[int]] | None = None
    source_scopes: list[set[str]] = []
    for position, source_unit in enumerate(source_units):
        if not pattern.search(source_unit):
            continue
        source_scope = _state_scope_terms(source_unit)
        if not source_scope:
            continue
        aligned = _best_aligned_claim(position, source_unit, rewritten_units)
        if aligned is None:
            if candidate_index is None:
                candidate_index = _candidate_index(rewritten_units)
            aligned = _best_aligned_claim(position, source_unit, rewritten_units, candidate_index)
        if aligned is not None and not pattern.search(aligned[1]):
            return ValidationWarning(
                kind=warning_kind,
                severity="high",
                value=label,
                message=(
                    "An explicit semantic state moved from one closely aligned material claim "
                    "to another. The candidate must be reviewed or rejected."
                ),
            )
        if aligned is not None:
            # A credible counterpart retaining the same explicit state is not
            # a relocation. Other guards still examine changed direction,
            # comparators, and status in that counterpart.
            continue
        source_scopes.append(source_scope)

    if not source_scopes:
        return None
    rewritten_scopes = [
        _state_scope_terms(unit)
        for unit in rewritten_units
        if pattern.search(unit) and _state_scope_terms(unit)
    ]
    # A lexical association below 80% is not treated as the same claim. This
    # catches a negation moved from "account transfer" to "asset sale" even
    # when both clauses share a generic actor or verb.
    for source_scope in source_scopes:
        if not any(_scope_similarity(source_scope, candidate_scope) >= 0.8 for candidate_scope in rewritten_scopes):
            return ValidationWarning(
                kind=warning_kind,
                severity="high",
                value=label,
                message=(
                    "An explicit semantic state is no longer associated with the same material claim. "
                    "The candidate must be reviewed or rejected."
                ),
            )
    return None


def _short_material_status_warning(
    source_claims: list[str],
    rewritten_claims: list[str],
) -> ValidationWarning | None:
    """Fail closed when a concise explicit status statement has no counterpart."""
    candidate_index: dict[str, list[int]] | None = None
    reviewed = 0
    for group_name, left_markers, right_markers in HIGH_RISK_STATUS_GROUPS:
        for source_position, source_claim in enumerate(source_claims):
            source_side, _left, _right = _marker_side(source_claim, left_markers, right_markers)
            if source_side is None or len(_claim_tokens(source_claim)) > 8:
                continue
            reviewed += 1
            if reviewed > HIGH_RISK_MAX_RISK_CLAIMS:
                return _high_risk_scan_limit_warning()
            aligned = _best_aligned_claim(source_position, source_claim, rewritten_claims)
            if aligned is None:
                if candidate_index is None:
                    candidate_index = _candidate_index(rewritten_claims)
                aligned = _best_aligned_claim(
                    source_position, source_claim, rewritten_claims, candidate_index
                )
            if aligned is not None:
                continue
            # A same-position sentence is a deliberately narrow fallback for
            # statements such as "Active." -> "Inactive." where lexical
            # alignment has no shared content token.
            same_position = (
                rewritten_claims[source_position]
                if source_position < len(rewritten_claims)
                else None
            )
            if same_position is not None:
                rewritten_side, _candidate_left, _candidate_right = _marker_side(
                    same_position, left_markers, right_markers
                )
                if rewritten_side is not None and rewritten_side != source_side:
                    return ValidationWarning(
                        kind="changed_material_status",
                        severity="high",
                        value=f"{group_name}: {source_side} -> {rewritten_side}",
                        message=(
                            "A short material status statement changed direction. "
                            "The candidate must be reviewed or rejected."
                        ),
                    )
            return ValidationWarning(
                kind="missing_material_status_claim",
                severity="high",
                value=group_name,
                message=(
                    "A short material status statement has no closely aligned counterpart. "
                    "The candidate must be reviewed or rejected."
                ),
            )
    return None


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


def _table_numeric_layout_warning(original: str, rewritten: str) -> ValidationWarning | None:
    """Reject a numeric Markdown-table cell or order change explicitly."""
    source_layouts = extract_numeric_table_layouts(original)
    if not source_layouts:
        return None
    if source_layouts == extract_numeric_table_layouts(rewritten):
        return None
    return ValidationWarning(
        kind="altered_table_numeric_layout",
        severity="high",
        value="numeric table cell or order",
        message=(
            "A numeric table cell, header, row, or column order changed. "
            "The candidate must be reviewed or rejected."
        ),
    )


def _payment_role_swap_warning(original: str, rewritten: str) -> ValidationWarning | None:
    """Catch a clear payer/recipient reversal without inferring broader roles."""
    source_pairs = {(item.payer, item.payee) for item in extract_payment_obligations(original)}
    if not source_pairs:
        return None
    rewritten_pairs = {(item.payer, item.payee) for item in extract_payment_obligations(rewritten)}
    for payer, payee in source_pairs:
        reversed_pair = (payee, payer)
        # Reciprocal obligations explicitly present in the source are not a
        # swap. A newly introduced reverse relation is unsafe by default.
        if reversed_pair in rewritten_pairs and reversed_pair not in source_pairs:
            return ValidationWarning(
                kind="swapped_payment_obligation_roles",
                severity="high",
                value=f"{payer} -> {payee}",
                message=(
                    "The payer and recipient in a clear payment obligation were reversed. "
                    "The candidate must be reviewed or rejected."
                ),
            )
    return None


def _global_reporting_period_warning(original: str, rewritten: str) -> ValidationWarning | None:
    """Handle a single explicit period even if sentence tokenization splits it."""
    source_periods = extract_reporting_periods(original)
    rewritten_periods = extract_reporting_periods(rewritten)
    if len(source_periods) == len(rewritten_periods) == 1 and source_periods != rewritten_periods:
        return ValidationWarning(
            kind="changed_reporting_period",
            severity="high",
            value=f"{source_periods[0]} -> {rewritten_periods[0]}",
            message=(
                "An explicit reporting quarter changed. The candidate must be reviewed or rejected."
            ),
        )
    return None


def _financial_marker_warning(
    source_claims: list[str],
    rewritten_claims: list[str],
) -> ValidationWarning | None:
    """Reject explicit quarter or monetary-scale changes in aligned claims."""
    candidate_index: dict[str, list[int]] | None = None
    reviewed = 0
    for source_position, source_claim in enumerate(source_claims):
        source_periods = extract_reporting_periods(source_claim)
        source_amounts = extract_monetary_amounts(source_claim)
        if not source_periods and not source_amounts:
            continue
        reviewed += 1
        if reviewed > HIGH_RISK_MAX_RISK_CLAIMS:
            return _high_risk_scan_limit_warning()
        aligned = _best_aligned_claim(source_position, source_claim, rewritten_claims)
        if aligned is None:
            if candidate_index is None:
                candidate_index = _candidate_index(rewritten_claims)
            aligned = _best_aligned_claim(source_position, source_claim, rewritten_claims, candidate_index)
        if aligned is None:
            continue
        _rewritten_position, rewritten_claim = aligned

        rewritten_periods = extract_reporting_periods(rewritten_claim)
        if len(source_periods) == len(rewritten_periods) == 1 and source_periods != rewritten_periods:
            return ValidationWarning(
                kind="changed_reporting_period",
                severity="high",
                value=f"{source_periods[0]} -> {rewritten_periods[0]}",
                message=(
                    "An explicit reporting quarter changed in a closely aligned claim. "
                    "The candidate must be reviewed or rejected."
                ),
            )

        rewritten_amounts = extract_monetary_amounts(rewritten_claim)
        if len(source_amounts) == len(rewritten_amounts) == 1:
            source_amount = source_amounts[0]
            rewritten_amount = rewritten_amounts[0]
            if (
                source_amount.currency == rewritten_amount.currency
                and source_amount.scale != rewritten_amount.scale
            ):
                return ValidationWarning(
                    kind="changed_monetary_scale",
                    severity="high",
                    value=(
                        f"{source_amount.currency.upper()} {source_amount.scale} "
                        f"-> {rewritten_amount.scale}"
                    ),
                    message=(
                        "The written scale of a currency amount changed in a closely aligned claim. "
                        "The candidate must be reviewed or rejected."
                    ),
                )
    return None


def _high_risk_claim_warnings(original: str, rewritten: str) -> list[ValidationWarning]:
    """Fail closed for explicit high-risk claim, threshold, and status changes.

    The comparison is intentionally limited to closely aligned claims. This avoids
    treating independent mentions of, for example, an approval and a rejection in
    different sentences as a semantic reversal.
    """
    if original == rewritten or _cleanup_artifact_equivalent(original) == rewritten:
        return []
    table_layout = _table_numeric_layout_warning(original, rewritten)
    if table_layout is not None:
        return [table_layout]
    payment_role_swap = _payment_role_swap_warning(original, rewritten)
    if payment_role_swap is not None:
        return [payment_role_swap]
    global_reporting_period = _global_reporting_period_warning(original, rewritten)
    if global_reporting_period is not None:
        return [global_reporting_period]
    source_claims = split_sentences(original)
    rewritten_claims = split_sentences(rewritten)
    if not source_claims:
        return []
    if not rewritten_claims:
        short_status = _short_material_status_warning(source_claims, rewritten_claims)
        return [short_status] if short_status is not None else []

    financial_marker = _financial_marker_warning(source_claims, rewritten_claims)
    if financial_marker is not None:
        return [financial_marker]

    # Do scope-preservation before the paired marker groups. A moved ``may``
    # would otherwise be reported only as a generic modal change, even though
    # the specific risk is that uncertainty moved to a different claim.
    source_units = _material_units(source_claims)
    rewritten_units = _material_units(rewritten_claims)
    for pattern, warning_kind, label in (
        (NEGATION, "altered_negation_scope", "negation moved between material claims"),
        (UNCERTAINTY, "altered_uncertainty_scope", "uncertainty moved between material claims"),
    ):
        moved_state = _moved_state_warning(
            source_units,
            rewritten_units,
            pattern=pattern,
            original_marker_count=len(pattern.findall(original)),
            rewritten_marker_count=len(pattern.findall(rewritten)),
            warning_kind=warning_kind,
            label=label,
        )
        if moved_state is not None:
            return [moved_state]

    candidate_terms: dict[str, list[int]] | None = None
    groups = (
        *(("changed_claim_polarity",) + group for group in HIGH_RISK_POLARITY_GROUPS),
        *(("changed_modal_obligation",) + group for group in HIGH_RISK_MODAL_GROUPS),
        *(("changed_claim_comparator",) + group for group in HIGH_RISK_COMPARATOR_GROUPS),
        *(("changed_material_status",) + group for group in HIGH_RISK_STATUS_GROUPS),
    )
    evaluated_claims = 0
    for warning_kind, group_name, left_markers, right_markers in groups:
        for source_position, source_claim in enumerate(source_claims):
            source_side, source_left, source_right = _marker_side(source_claim, left_markers, right_markers)
            if source_side is None:
                continue
            evaluated_claims += 1
            if evaluated_claims > HIGH_RISK_MAX_RISK_CLAIMS:
                return [_high_risk_scan_limit_warning()]
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
            return [ValidationWarning(
                kind=warning_kind,
                severity="high",
                value=f"{group_name}: {before_label} -> {after_label}",
                message=(
                    "A high-risk polarity, direction, comparator, modal, or status statement changed "
                    "in a closely aligned claim. "
                    "The candidate must be reviewed or rejected."
                ),
            )]
            # One confirmed high-severity inversion rejects the candidate. It is
            # sufficient for a safe fallback and keeps both the audit and the UI
            # bounded for documents containing repeated template sentences.

    short_status = _short_material_status_warning(source_claims, rewritten_claims)
    if short_status is not None:
        return [short_status]
    return []


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
