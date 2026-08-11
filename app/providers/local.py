from __future__ import annotations

import re
import unicodedata

from app.models import RewriteStrength, SemanticConstraints, TransformOptions
from app.providers.base import EditorialProvider

class LocalRuleProvider(EditorialProvider):
    """Conservative format cleaner; no text or features leave the machine."""

    name = "rules"

    def rewrite(self, text: str, constraints: SemanticConstraints, options: TransformOptions) -> str:
        result = text.replace("\r\n", "\n").replace("\r", "\n")
        result = unicodedata.normalize("NFC", result)
        result = result.replace("\ufeff", "").replace("\u200b", "").replace("\u00ad", "")
        result = result.replace("\u00a0", " ").replace("\u202f", " ")
        # Markdown hard breaks (two trailing spaces) and code whitespace are preserved.
        if options.rewrite_strength == RewriteStrength.SUBSTANTIAL:
            result = re.sub(r"\n{3,}", "\n\n", result)
        return result
