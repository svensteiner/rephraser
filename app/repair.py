"""Narrow deterministic repairs for harmless model formatting artifacts."""

from __future__ import annotations

from app.models import SemanticConstraints


def repair_protected_formatting(
    original: str, rewritten: str, constraints: SemanticConstraints
) -> str:
    """Restore exact raw-URL formatting without relaxing semantic validation."""
    result = rewritten
    for citation in constraints.citations:
        wrapped = f"<{citation}>"
        if citation in original and wrapped not in original:
            result = result.replace(wrapped, citation)
    return result
