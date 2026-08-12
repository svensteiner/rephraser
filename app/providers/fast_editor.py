"""Instant conservative editorial improvements for common business prose."""

from __future__ import annotations

import re

from app.models import SemanticConstraints, TransformOptions
from app.providers.base import EditorialProvider
from app.providers.local import LocalRuleProvider
from app.protection import transform_outside_protected_terms


PROTECTED_PROSE = re.compile(
    r"(\A---\r?\n[\s\S]*?\r?\n---(?=\r?\n|$)|(?:```|~~~)[\s\S]*?(?:```|~~~)|"
    r"^(?: {4}|\t).*$|^>.*$|``[^\n]*?``|`[^`\n]+`|<https?://[^>\n]+>|"
    r"\]\([^\)\n]+\)|"
    r"\"[^\"\n]+\"|„[^“\n]+“|“[^”\n]+”|»[^«\n]+«|«[^»\n]+»|‘[^’\n]+’)",
    re.MULTILINE,
)

REPLACEMENTS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bWe would like to better understand\b"), "We would appreciate clarification on"),
    (re.compile(r"\bwe would like to better understand\b"), "we would appreciate clarification on"),
    (re.compile(r"\bYou mentioned that\b"), "You noted that"),
    (re.compile(r"\bCould you please clarify:\s*(?=\n|$)"), "Could you please clarify the following:"),
    (re.compile(r"\bIn order to\b"), "To"),
    (re.compile(r"\bDue to the fact that\b"), "Because"),
    (re.compile(r"\bdue to the fact that\b"), "because"),
    (re.compile(r"\bAt this point in time\b"), "Currently"),
    (re.compile(r"\bPlease do not hesitate to\b"), "Please"),
    (re.compile(r"\bWir möchten gerne\b"), "Wir möchten"),
    (re.compile(r"\bEs ist wichtig zu beachten, dass\b"), "Zu beachten ist, dass"),
    (re.compile(r"\bZum jetzigen Zeitpunkt\b"), "Derzeit"),
    (re.compile(r"\bzum jetzigen Zeitpunkt\b"), "derzeit"),
    (re.compile(r"\bAufgrund der Tatsache, dass\b"), "Weil"),
    (re.compile(r"\baufgrund der Tatsache, dass\b"), "weil"),
)


def _apply_replacements(text: str) -> str:
    for pattern, replacement in REPLACEMENTS:
        text = pattern.sub(replacement, text)
    return text


def _edit_unprotected_prose(text: str, protected_terms: list[str] | tuple[str, ...] = ()) -> str:
    parts = PROTECTED_PROSE.split(text)
    for index in range(0, len(parts), 2):
        parts[index] = transform_outside_protected_terms(parts[index], protected_terms, _apply_replacements)
    return "".join(parts)


class FastEditorialProvider(EditorialProvider):
    """Apply narrowly scoped, tested prose improvements without a model."""

    name = "fast-editor"

    def rewrite(self, text: str, constraints: SemanticConstraints, options: TransformOptions) -> str:
        cleaned = LocalRuleProvider().rewrite(text, constraints, options)
        return _edit_unprotected_prose(cleaned, constraints.protected_terms)
