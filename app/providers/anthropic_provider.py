from __future__ import annotations

from app.models import SemanticConstraints, TransformOptions
from app.providers.base import EditorialProvider, ProviderError


class AnthropicProvider(EditorialProvider):
    name = "anthropic"
    is_remote = True

    def rewrite(self, text: str, constraints: SemanticConstraints, options: TransformOptions) -> str:
        raise ProviderError(
            "The cloud Anthropic adapter is intentionally disabled in the local-first build. "
            "Enabling it requires an explicit implementation and data-transmission review."
        )
