from __future__ import annotations

from .models import SemanticConstraints, TransformOptions
from .providers.base import EditorialProvider


def rewrite_text(text: str, constraints: SemanticConstraints, options: TransformOptions,
                 provider: EditorialProvider) -> str:
    return provider.rewrite(text, constraints, options)
