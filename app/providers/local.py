from __future__ import annotations

import re
import unicodedata

from app.models import RewriteStrength, SemanticConstraints, TransformOptions
from app.protection import transform_outside_protected_terms
from app.providers.base import EditorialProvider


FENCED_BLOCK = re.compile(
    r"^(?P<fence>`{3,}|~{3,})[^\n]*\n[\s\S]*?^(?P=fence)[ \t]*(?:\n|$)", re.MULTILINE
)


def _collapse_blank_lines_outside_fences(text: str) -> str:
    pieces: list[str] = []
    cursor = 0
    for match in FENCED_BLOCK.finditer(text):
        pieces.append(re.sub(r"\n{3,}", "\n\n", text[cursor:match.start()]))
        pieces.append(match.group(0))
        cursor = match.end()
    pieces.append(re.sub(r"\n{3,}", "\n\n", text[cursor:]))
    return "".join(pieces)

class LocalRuleProvider(EditorialProvider):
    """Conservative format cleaner; no text or features leave the machine."""

    name = "rules"

    def rewrite(self, text: str, constraints: SemanticConstraints, options: TransformOptions) -> str:
        def clean_fragment(fragment: str) -> str:
            cleaned = fragment.replace("\r\n", "\n").replace("\r", "\n")
            cleaned = unicodedata.normalize("NFC", cleaned)
            cleaned = cleaned.replace("\u200b", "").replace("\u00ad", "")
            return cleaned.replace("\u00a0", " ").replace("\u202f", " ")

        result = transform_outside_protected_terms(text, constraints.protected_terms, clean_fragment)
        # A BOM is only unambiguous at the beginning of a document. Explicit
        # terms cannot contain format controls, so a leading BOM is never protected.
        if result.startswith("\ufeff"):
            result = result[1:]
        # Markdown hard breaks (two trailing spaces) and code whitespace are preserved.
        if options.rewrite_strength == RewriteStrength.SUBSTANTIAL:
            result = _collapse_blank_lines_outside_fences(result)
        return result
