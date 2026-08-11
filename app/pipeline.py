from __future__ import annotations

from datetime import datetime, timezone
import difflib
import hashlib

from .diff import create_diff
from .inspection import inspect_text
from .metrics import calculate_metrics
from .models import AuditReport, TransformOptions, TransformResult, Transformation, ValidationWarning
from .providers.base import EditorialProvider, ProviderError
from .providers.fast_editor import FastEditorialProvider
from .providers.local import LocalRuleProvider
from .providers.mistral_provider import LocalMistralProvider
from .providers.hybrid import HybridLocalProvider
from .repair import repair_protected_formatting
from .rewrite import rewrite_text
from .semantic import extract_semantics
from .validation import validate_preservation

PIPELINE_VERSION = "1.3.0"


def get_provider(name: str) -> EditorialProvider:
    normalized = name.casefold()
    if normalized in {"local", "rules", "rule-based"}:
        return LocalRuleProvider()
    if normalized in {"fast", "fast-rules", "fast-editor"}:
        return FastEditorialProvider()
    if normalized in {"mistral", "mistral-local", "ollama"}:
        return LocalMistralProvider()
    if normalized in {"auto", "hybrid", "rules+mistral-local"}:
        return HybridLocalProvider()
    if normalized in {"openai", "anthropic"}:
        raise ProviderError(f"Remote provider '{name}' is disabled; select fast-editor, rules, or mistral-local.")
    raise ProviderError(f"Unknown provider: {name}")


def run_pipeline(text: str, options: TransformOptions | None = None,
                 provider: EditorialProvider | None = None) -> TransformResult:
    selected = options or TransformOptions()
    inspection = inspect_text(text)
    semantics = extract_semantics(text)
    before_metrics = calculate_metrics(text)
    active_provider = provider or get_provider(selected.provider)
    provider_failure: ProviderError | None = None
    try:
        rewritten = rewrite_text(text, semantics, selected, active_provider)
        rewritten = repair_protected_formatting(text, rewritten, semantics)
    except ProviderError as error:
        if "mistral" not in active_provider.name:
            raise
        provider_failure = error
        rewritten = LocalRuleProvider().rewrite(text, semantics, selected)
    warnings = validate_preservation(text, rewritten, semantics,
        preserve_numbers=selected.preserve_numbers, preserve_citations=selected.preserve_citations,
        preserve_quotations=selected.preserve_quotations)
    if provider_failure is not None:
        warnings.append(ValidationWarning(
            kind="provider_unavailable",
            severity="medium",
            value=type(provider_failure).__name__,
            message=("Das lokale Sprachmodell war nicht rechtzeitig verfügbar. "
                     "Ausgegeben wurde nur die sichere Grundbereinigung."),
        ))
    elif ("mistral" in active_provider.name or active_provider.name == "fast-editor") and warnings:
        rejected_count = len(warnings)
        rewritten = LocalRuleProvider().rewrite(text, semantics, selected)
        warnings = validate_preservation(text, rewritten, semantics,
            preserve_numbers=selected.preserve_numbers, preserve_citations=selected.preserve_citations,
            preserve_quotations=selected.preserve_quotations)
        rejected_source = "Modellfassung" if "mistral" in active_provider.name else "Schnellbearbeitung"
        warnings.append(ValidationWarning(
            kind="rewrite_rejected",
            severity="medium",
            value=str(rejected_count),
            message=(f"Die sprachliche {rejected_source} wurde wegen möglicher inhaltlicher Änderungen "
                     "verworfen. Ausgegeben wurde nur die sichere Grundbereinigung."),
        ))
    transformations = []
    matcher = difflib.SequenceMatcher(None, text, rewritten)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag != "equal":
            transformations.append(Transformation(kind=tag, before=text[i1:i2], after=rewritten[j1:j2],
                reason=f"{active_provider.name} editorial transformation at original offsets {i1}:{i2}",
                original_start=i1, original_end=i2, rewritten_start=j1, rewritten_end=j2))
    audit = AuditReport(original_hash=hashlib.sha256(text.encode("utf-8")).hexdigest(),
        timestamp=datetime.now(timezone.utc), pipeline_version=PIPELINE_VERSION,
        inspection=inspection, inspection_after=inspect_text(rewritten),
        semantic_constraints=semantics, transformations=transformations,
        fact_preservation_warnings=warnings, quality_metrics_before=before_metrics,
        quality_metrics_after=calculate_metrics(rewritten), diff=create_diff(text, rewritten),
        safeguard=("Editorial and provenance audit only. No AI probability is calculated, and no "
                   "watermark or AI-detection bypass is attempted or claimed."))
    return TransformResult(rewritten_text=rewritten, audit=audit)
