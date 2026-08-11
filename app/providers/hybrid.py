from __future__ import annotations

from app.models import SemanticConstraints, TransformOptions
from app.providers.base import EditorialProvider
from app.providers.local import LocalRuleProvider
from app.providers.mistral_provider import LocalMistralProvider


class HybridLocalProvider(EditorialProvider):
    """Deterministic cleanup followed by a local Mistral editorial pass."""

    name = "rules+mistral-local"

    def __init__(self) -> None:
        self.rules = LocalRuleProvider()
        self.mistral = LocalMistralProvider()

    def rewrite(self, text: str, constraints: SemanticConstraints, options: TransformOptions) -> str:
        cleaned = self.rules.rewrite(text, constraints, options)
        return self.mistral.rewrite(cleaned, constraints, options)
