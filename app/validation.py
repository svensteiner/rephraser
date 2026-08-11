from __future__ import annotations

import re

from .models import SemanticConstraints, ValidationWarning
from .semantic import DATE, NUMBER, URL, extract_semantics


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
    return warnings
