from __future__ import annotations

import re
import unicodedata

from app.models import RewriteStrength, SemanticConstraints, TransformOptions
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
        result = text.replace("\r\n", "\n").replace("\r", "\n")
        result = unicodedata.normalize("NFC", result)
        # A BOM is only unambiguous at the beginning of a document. Mid-text
        # U+FEFF is retained and surfaced by inspection instead of being
        # silently deleted as an unknown copy/paste pattern.
        if result.startswith("\ufeff"):
            result = result[1:]
        result = result.replace("\u200b", "").replace("\u00ad", "")
        result = result.replace("\u00a0", " ").replace("\u202f", " ")
        # Markdown hard breaks (two trailing spaces) and code whitespace are preserved.
        if options.rewrite_strength == RewriteStrength.SUBSTANTIAL:
            result = _collapse_blank_lines_outside_fences(result)
        return result
