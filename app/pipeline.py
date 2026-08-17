from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import difflib
import hashlib
import re
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
from .protection import missing_protected_terms
from .repair import repair_protected_formatting
from .rewrite import rewrite_text
from .semantic import extract_semantics
from .validation import validate_preservation

PIPELINE_VERSION = "1.16.0"


# A character-level SequenceMatcher gives useful, exact offsets for ordinary
# documents, but has quadratic worst cases.  A long copied template can make
# audit construction look like the editor has stopped responding.  Keep the
# detailed trail comfortably below that risk and make every summary explicit.
_MAX_DETAILED_TRANSFORMATION_CHARACTERS = 16_000
_MAX_DETAILED_TRANSFORMATION_OPCODES = 400
_MAX_ATOMIC_TRANSFORMATION_CHARACTERS = 4_000
_REPETITIVE_AUDIT_MINIMUM_TOKENS = 256
_REPETITIVE_AUDIT_WINDOW_TOKENS = 4
_REPETITIVE_AUDIT_MINIMUM_WINDOWS = 32


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


def _has_repetitive_token_windows(value: str) -> bool:
    """Identify copied template structure without treating common words as repetition."""
    tokens = re.findall(r"\S+", value)
    if len(tokens) < _REPETITIVE_AUDIT_MINIMUM_TOKENS:
        return False
    windows = Counter(
        tuple(tokens[position:position + _REPETITIVE_AUDIT_WINDOW_TOKENS])
        for position in range(0, len(tokens) - _REPETITIVE_AUDIT_WINDOW_TOKENS + 1,
                              _REPETITIVE_AUDIT_WINDOW_TOKENS)
    )
    if not windows:
        return False
    repeated_windows = windows.most_common(1)[0][1]
    return (
        repeated_windows >= _REPETITIVE_AUDIT_MINIMUM_WINDOWS
        and repeated_windows * 12 >= sum(windows.values())
    )


def _transformation_audit_limit_reason(original: str, rewritten: str) -> str | None:
    largest_text = max(len(original), len(rewritten))
    if largest_text > _MAX_DETAILED_TRANSFORMATION_CHARACTERS:
        return (
            f"the source or result exceeds {_MAX_DETAILED_TRANSFORMATION_CHARACTERS:,} characters"
        )
    if _has_repetitive_token_windows(original) or _has_repetitive_token_windows(rewritten):
        return "the source or result contains strongly repeated token sequences"
    return None


def _bounded_transformation_audit(
    original: str,
    rewritten: str,
    reason: str,
) -> tuple[list[Transformation], ValidationWarning]:
    """Return an honest aggregate record when individual character edits are unsafe.

    Empty before/after values deliberately point to zero-length ranges.  They
    are not excerpts of the text and therefore cannot be mistaken for a full
    edit record; the reason and warning carry the aggregate metadata.
    """
    detail = (
        "Detailed character-level edit positions were intentionally not enumerated because "
        f"{reason}. The whole-document hashes, Unicode inspection, and bounded diff remain in "
        "the audit."
    )
    transformation = Transformation(
        kind="bounded_summary",
        before="",
        after="",
        reason=detail,
        code_points_before=[],
        code_points_after=[],
        original_start=0,
        original_end=0,
        rewritten_start=0,
        rewritten_end=0,
    )
    warning = ValidationWarning(
        kind="transformation_audit_truncated",
        severity="low",
        value=(
            f"original_characters={len(original)}; rewritten_characters={len(rewritten)}; "
            f"reason={reason}"
        ),
        message=(
            "The character-level transformation list is an aggregate summary, not a complete "
            "enumeration of edits."
        ),
    )
    return [transformation], warning


def _build_transformations(
    original: str,
    rewritten: str,
    provider_name: str,
) -> tuple[list[Transformation], ValidationWarning | None]:
    """Build detailed transformations only while their cost and size stay bounded."""
    if original == rewritten:
        return [], None

    limit_reason = _transformation_audit_limit_reason(original, rewritten)
    if limit_reason is not None:
        return _bounded_transformation_audit(original, rewritten, limit_reason)

    matcher = difflib.SequenceMatcher(None, original, rewritten)
    changes = [opcode for opcode in matcher.get_opcodes() if opcode[0] != "equal"]
    if len(changes) > _MAX_DETAILED_TRANSFORMATION_OPCODES:
        return _bounded_transformation_audit(
            original,
            rewritten,
            f"the rewrite contains more than {_MAX_DETAILED_TRANSFORMATION_OPCODES:,} edit regions",
        )
    if any(max(i2 - i1, j2 - j1) > _MAX_ATOMIC_TRANSFORMATION_CHARACTERS
           for _tag, i1, i2, j1, j2 in changes):
        return _bounded_transformation_audit(
            original,
            rewritten,
            "one edit region exceeds the bounded atomic audit size",
        )

    transformations = []
    for tag, i1, i2, j1, j2 in changes:
        before, after = original[i1:i2], rewritten[j1:j2]
        transformations.append(Transformation(
            kind=tag,
            before=before,
            after=after,
            reason=_transformation_reason(before, after, provider_name),
            code_points_before=_code_points(before),
            code_points_after=_code_points(after),
            original_start=i1,
            original_end=i2,
            rewritten_start=j1,
            rewritten_end=j2,
        ))
    return transformations, None


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
    semantics = extract_semantics(text, selected.protected_terms)
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
    for missing_term in missing_protected_terms(text, selected.protected_terms):
        warnings.append(ValidationWarning(
            kind="protected_term_not_found",
            severity="medium",
            value=missing_term,
            message="Der gewünschte geschützte Begriff kommt im Ausgangstext nicht exakt vor.",
        ))
    transformations, transformation_audit_warning = _build_transformations(
        text, rewritten, applied_provider
    )
    if transformation_audit_warning is not None:
        warnings.append(transformation_audit_warning)
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
