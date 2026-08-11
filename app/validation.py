from __future__ import annotations

import re

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


def validate_preservation(original: str, rewritten: str, constraints: SemanticConstraints,
                          *, preserve_numbers: bool = True, preserve_citations: bool = True,
                          preserve_quotations: bool = True) -> list[ValidationWarning]:
    warnings: list[ValidationWarning] = []
    checks = (("number", constraints.numbers if preserve_numbers else []),
              ("date", constraints.dates if preserve_numbers else []),
              ("proper_name", constraints.names),
              ("citation", constraints.citations if preserve_citations else []),
              ("quotation", constraints.quotations if preserve_quotations else []))
    for kind, values in checks:
        for value in values:
            if value not in rewritten:
                warnings.append(ValidationWarning(kind=f"missing_{kind}", severity="high", value=value,
                    message=f"Original {kind.replace('_', ' ')} is absent or changed in the rewrite."))
            elif kind in {"number", "date", "citation", "quotation"} and original.count(value) != rewritten.count(value):
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
    for kind, values, originals in (
        ("number", new_semantics.numbers if preserve_numbers else [], constraints.numbers),
        ("date", new_semantics.dates if preserve_numbers else [], constraints.dates),
        ("proper_name", new_semantics.names, constraints.names),
        ("citation", new_semantics.citations if preserve_citations else [], constraints.citations),
        ("quotation", new_semantics.quotations if preserve_quotations else [], constraints.quotations),
    ):
        for value in values:
            if value not in originals:
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

    association_groups = [
        ("numeric", constraints.numbers if preserve_numbers else []),
        ("date", constraints.dates if preserve_numbers else []),
        ("proper_name", constraints.names),
        ("citation", constraints.citations if preserve_citations else []),
        ("quotation", constraints.quotations if preserve_quotations else []),
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
