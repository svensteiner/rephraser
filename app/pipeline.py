from __future__ import annotations

from datetime import datetime, timezone
import difflib
import hashlib
import unicodedata

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

PIPELINE_VERSION = "1.5.2"


def _code_points(value: str) -> list[str]:
    return [f"U+{ord(character):04X}" for character in value]


def _transformation_reason(before: str, after: str, provider_name: str) -> str:
    """Describe deterministic cleanup precisely; retain a truthful generic fallback."""
    if before == "\r" and after == "":
        return "Normalize CRLF line ending to LF"
    if before == "\r" and after == "\n":
        return "Normalize CR line ending to LF"
    if before and not after and set(before) <= {"\u200b"}:
        return "Remove zero-width space copy/paste artifact"
    if before and not after and set(before) <= {"\u00ad"}:
        return "Remove invisible soft-hyphen copy/paste artifact"
    if before == "\ufeff" and not after:
        return "Remove leading Unicode byte-order mark"
    if before and len(before) == len(after) and set(before) <= {"\u00a0", "\u202f"} and set(after) <= {" "}:
        return "Replace non-breaking space with regular space"
    if before and unicodedata.normalize("NFC", before) == after:
        return "Normalize Unicode sequence to NFC"
    return f"{provider_name} editorial transformation"


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
    requested_provider = active_provider.name
    applied_provider = requested_provider
    provider_failure: ProviderError | None = None
    try:
        rewritten = rewrite_text(text, semantics, selected, active_provider)
        rewritten = repair_protected_formatting(text, rewritten, semantics)
    except ProviderError as error:
        if "mistral" not in active_provider.name:
            raise
        provider_failure = error
        if error.code == "model_input_too_long":
            rewritten = FastEditorialProvider().rewrite(text, semantics, selected)
            applied_provider = FastEditorialProvider.name
        else:
            rewritten = LocalRuleProvider().rewrite(text, semantics, selected)
            applied_provider = LocalRuleProvider.name
    warnings = validate_preservation(text, rewritten, semantics,
        preserve_numbers=selected.preserve_numbers, preserve_citations=selected.preserve_citations,
        preserve_quotations=selected.preserve_quotations)
    if provider_failure is not None:
        if applied_provider == FastEditorialProvider.name and warnings:
            rejection_kinds = sorted({warning.kind for warning in warnings})
            rewritten = LocalRuleProvider().rewrite(text, semantics, selected)
            applied_provider = LocalRuleProvider.name
            warnings = validate_preservation(
                text, rewritten, semantics,
                preserve_numbers=selected.preserve_numbers,
                preserve_citations=selected.preserve_citations,
                preserve_quotations=selected.preserve_quotations,
            )
            warnings.append(ValidationWarning(
                kind="rewrite_rejected",
                severity="medium",
                value=", ".join(rejection_kinds),
                message=("Die lokale Schnellbearbeitung wurde wegen möglicher inhaltlicher Änderungen "
                         "verworfen. Ausgegeben wurde nur die sichere Grundbereinigung."),
            ))
        failure_kind = {
            "model_input_too_long": "model_input_too_long",
            "provider_timeout": "provider_timeout",
        }.get(provider_failure.code, "provider_unavailable")
        failure_message = {
            "model_input_too_long": (
                "Der Text ist für einen einzelnen lokalen Modelldurchlauf zu lang. "
                "Ausgegeben wurde die sichere lokale Schnellbearbeitung."
            ),
            "provider_timeout": (
                "Das lokale Sprachmodell hat die Gesamtdauer überschritten. "
                "Ausgegeben wurde nur die sichere Grundbereinigung."
            ),
        }.get(
            provider_failure.code,
            "Das lokale Sprachmodell war nicht verfügbar. Ausgegeben wurde nur die sichere Grundbereinigung.",
        )
        warnings.append(ValidationWarning(
            kind=failure_kind,
            severity="medium",
            value=provider_failure.code,
            message=failure_message,
        ))
    elif ("mistral" in active_provider.name or active_provider.name == "fast-editor") and warnings:
        rejection_kinds = sorted({warning.kind for warning in warnings})
        rewritten = LocalRuleProvider().rewrite(text, semantics, selected)
        applied_provider = LocalRuleProvider.name
        warnings = validate_preservation(text, rewritten, semantics,
            preserve_numbers=selected.preserve_numbers, preserve_citations=selected.preserve_citations,
            preserve_quotations=selected.preserve_quotations)
        rejected_source = "Modellfassung" if "mistral" in active_provider.name else "Schnellbearbeitung"
        warnings.append(ValidationWarning(
            kind="rewrite_rejected",
            severity="medium",
            value=", ".join(rejection_kinds),
            message=(f"Die sprachliche {rejected_source} wurde wegen möglicher inhaltlicher Änderungen "
                     "verworfen. Ausgegeben wurde nur die sichere Grundbereinigung."),
        ))
    transformations = []
    matcher = difflib.SequenceMatcher(None, text, rewritten)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag != "equal":
            before, after = text[i1:i2], rewritten[j1:j2]
            transformations.append(Transformation(kind=tag, before=before, after=after,
                reason=_transformation_reason(before, after, applied_provider),
                code_points_before=_code_points(before), code_points_after=_code_points(after),
                original_start=i1, original_end=i2, rewritten_start=j1, rewritten_end=j2))
    audit = AuditReport(original_hash=hashlib.sha256(text.encode("utf-8")).hexdigest(),
        output_hash=hashlib.sha256(rewritten.encode("utf-8")).hexdigest(),
        timestamp=datetime.now(timezone.utc), pipeline_version=PIPELINE_VERSION,
        requested_provider=requested_provider, applied_provider=applied_provider,
        options=selected.model_dump(mode="json"),
        inspection=inspection, inspection_after=inspect_text(rewritten),
        semantic_constraints=semantics, transformations=transformations,
        fact_preservation_warnings=warnings, quality_metrics_before=before_metrics,
        quality_metrics_after=calculate_metrics(rewritten), diff=create_diff(text, rewritten),
        safeguard=("Editorial and provenance audit only. No AI probability is calculated, and no "
                   "watermark or AI-detection bypass is attempted or claimed."))
    return TransformResult(rewritten_text=rewritten, audit=audit)
