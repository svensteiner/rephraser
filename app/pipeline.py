from __future__ import annotations

from datetime import datetime, timezone
import difflib
import hashlib

from .diff import create_diff
from .inspection import inspect_text
from .metrics import calculate_metrics
from .models import AuditReport, TransformOptions, TransformResult, Transformation, ValidationWarning
from .providers.base import EditorialProvider, ProviderError
from .providers.local import LocalRuleProvider
from .providers.mistral_provider import LocalMistralProvider
from .providers.hybrid import HybridLocalProvider
from .rewrite import rewrite_text
from .semantic import extract_semantics
from .validation import validate_preservation

PIPELINE_VERSION = "1.0.0"


def get_provider(name: str) -> EditorialProvider:
    normalized = name.casefold()
    if normalized in {"local", "rules", "rule-based"}:
        return LocalRuleProvider()
    if normalized in {"mistral", "mistral-local", "ollama"}:
        return LocalMistralProvider()
    if normalized in {"auto", "hybrid", "rules+mistral-local"}:
        return HybridLocalProvider()
    if normalized in {"openai", "anthropic"}:
        raise ProviderError(f"Remote provider '{name}' is disabled; select rules or mistral-local.")
    raise ProviderError(f"Unknown provider: {name}")


def run_pipeline(text: str, options: TransformOptions | None = None,
                 provider: EditorialProvider | None = None) -> TransformResult:
    selected = options or TransformOptions()
    inspection = inspect_text(text)
    semantics = extract_semantics(text)
    before_metrics = calculate_metrics(text)
    active_provider = provider or get_provider(selected.provider)
    rewritten = rewrite_text(text, semantics, selected, active_provider)
    warnings = validate_preservation(text, rewritten, semantics,
        preserve_numbers=selected.preserve_numbers, preserve_citations=selected.preserve_citations,
        preserve_quotations=selected.preserve_quotations)
    if "mistral" in active_provider.name and warnings:
        rejected_count = len(warnings)
        rewritten = LocalRuleProvider().rewrite(text, semantics, selected)
        warnings = validate_preservation(text, rewritten, semantics,
            preserve_numbers=selected.preserve_numbers, preserve_citations=selected.preserve_citations,
            preserve_quotations=selected.preserve_quotations)
        warnings.append(ValidationWarning(
            kind="rewrite_rejected",
            severity="medium",
            value=str(rejected_count),
            message=("Die sprachliche Modellfassung wurde wegen möglicher inhaltlicher Änderungen "
                     "verworfen. Ausgegeben wurde nur die sichere Grundbereinigung."),
        ))
    transformations = []
    matcher = difflib.SequenceMatcher(None, text, rewritten)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag != "equal":
            transformations.append(Transformation(kind=tag, before=text[i1:i2], after=rewritten[j1:j2],
                reason=f"{active_provider.name} editorial transformation at original offsets {i1}:{i2}"))
    audit = AuditReport(original_hash=hashlib.sha256(text.encode("utf-8")).hexdigest(),
        timestamp=datetime.now(timezone.utc), pipeline_version=PIPELINE_VERSION,
        inspection=inspection, semantic_constraints=semantics, transformations=transformations,
        fact_preservation_warnings=warnings, quality_metrics_before=before_metrics,
        quality_metrics_after=calculate_metrics(rewritten), diff=create_diff(text, rewritten),
        safeguard=("Editorial and provenance audit only. No AI probability is calculated, and no "
                   "watermark or AI-detection bypass is attempted or claimed."))
    return TransformResult(rewritten_text=rewritten, audit=audit)
