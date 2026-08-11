from __future__ import annotations

from abc import ABC, abstractmethod

from app.models import SemanticConstraints, TransformOptions


class ProviderError(RuntimeError):
    """Raised when a selected provider cannot safely complete a rewrite."""

    def __init__(self, message: str, *, code: str = "provider_unavailable") -> None:
        super().__init__(message)
        self.code = code


class EditorialProvider(ABC):
    name: str
    is_remote: bool = False

    @abstractmethod
    def rewrite(self, text: str, constraints: SemanticConstraints, options: TransformOptions) -> str:
        """Return edited text or raise ProviderError. Never silently switch providers."""
