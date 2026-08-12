"""Honest, user-facing summaries of automated semantic preservation checks."""

from __future__ import annotations

from dataclasses import dataclass

from app.models import SemanticConstraints, ValidationWarning


NON_CONTENT_WARNINGS = {
    "model_input_too_long",
    "provider_timeout",
    "provider_unavailable",
    "user_selected_safe_fallback",
}


@dataclass(frozen=True, slots=True)
class ReviewSummary:
    level: str
    title: str
    message: str
    checked_values: str
    notices: tuple[str, ...]


def _count_label(count: int, singular: str, plural: str) -> str:
    return f"{count} {singular if count == 1 else plural}"


def _checked_values(constraints: SemanticConstraints) -> str:
    number_dates = len(dict.fromkeys([*constraints.numbers, *constraints.dates]))
    parts = [
        _count_label(number_dates, "Zahl/Datum", "Zahlen/Daten"),
        _count_label(len(dict.fromkeys(constraints.names)), "Name", "Namen"),
        _count_label(len(dict.fromkeys(constraints.citations)), "Quelle/Link", "Quellen/Links"),
        _count_label(len(dict.fromkeys(constraints.quotations)), "Zitat", "Zitate"),
        _count_label(len(constraints.core_claims), "Aussage", "Aussagen"),
    ]
    if constraints.protected_terms:
        parts.append(_count_label(len(constraints.protected_terms), "eigener Begriff", "eigene Begriffe"))
    return "Automatisch geprüft: " + " · ".join(parts)


def _notice(warning: ValidationWarning) -> str:
    if warning.kind == "provider_timeout":
        return "Mistral überschritt die Zeitgrenze; geprüft wurde die sichere lokale Ersatzfassung."
    if warning.kind == "provider_unavailable":
        return "Mistral war nicht verfügbar; geprüft wurde die sichere lokale Ersatzfassung."
    if warning.kind == "model_input_too_long":
        return "Der Text war für einen Modelldurchlauf zu lang; geprüft wurde die lokale Schnellfassung."
    if warning.kind == "rewrite_rejected":
        return "Eine möglicherweise inhaltlich veränderte Fassung wurde automatisch verworfen."
    if warning.kind == "user_selected_safe_fallback":
        return "Die sichere lokale Schnellfassung wurde auf Wunsch sofort verwendet."
    if warning.kind == "protected_term_not_found":
        return f"Gewünschter geschützter Begriff nicht im Ausgangstext gefunden: {warning.value}"
    labels = {
        "altered_negation": "Verneinung möglicherweise verändert",
        "altered_uncertainty": "Unsicherheit möglicherweise verändert",
        "altered_markdown_structure": "Markdown-Struktur möglicherweise verändert",
        "missing_or_reassigned_claim": "Aussage möglicherweise entfernt oder verschoben",
        "unsupported_new_claim": "Neue Aussage sollte inhaltlich geprüft werden",
    }
    label = labels.get(warning.kind)
    if label is None:
        if warning.kind.startswith("missing_"):
            label = "Geschützter Wert fehlt möglicherweise"
        elif warning.kind.startswith("new_"):
            label = "Neuer Wert wurde möglicherweise ergänzt"
        elif warning.kind.startswith("reassigned_"):
            label = "Wert wurde möglicherweise einer anderen Aussage zugeordnet"
        elif warning.kind.startswith("altered_"):
            label = "Geschützter Inhalt wurde möglicherweise verändert"
        else:
            label = "Inhaltlicher Prüfhinweis"
    return f"{label}: {warning.value}" if warning.value else label


def build_review_summary(
    constraints: SemanticConstraints,
    warnings: list[ValidationWarning],
) -> ReviewSummary:
    """Describe what automated checks established without claiming semantic proof."""
    blocking = [
        warning for warning in warnings
        if warning.kind not in NON_CONTENT_WARNINGS and warning.kind != "rewrite_rejected"
    ]
    rejected = any(warning.kind == "rewrite_rejected" for warning in warnings)
    notices = tuple(dict.fromkeys(_notice(warning) for warning in warnings))
    checked = _checked_values(constraints)
    if blocking:
        return ReviewSummary(
            level="review",
            title="⚠ Bitte inhaltlich prüfen",
            message=(
                "Die automatische Prüfung hat mögliche Abweichungen gefunden. "
                "Vergleiche die markierten Stellen vor dem Kopieren."
            ),
            checked_values=checked,
            notices=notices,
        )
    if rejected:
        return ReviewSummary(
            level="protected",
            title="✓ Unsichere Fassung automatisch verworfen",
            message=(
                "Angezeigt wird die sichere Ersatzfassung. Die Prüfung hat keine verbleibende "
                "Abweichung bei den überwachten Inhalten gefunden."
            ),
            checked_values=checked,
            notices=notices,
        )
    return ReviewSummary(
        level="passed",
        title="✓ Automatische Inhaltsprüfung bestanden",
        message=(
            "Keine Abweichung bei den überwachten Zahlen, Daten, Namen, Quellen, Zitaten, "
            "Verneinungen oder Unsicherheiten gefunden. Bitte wichtige Texte dennoch selbst lesen."
        ),
        checked_values=checked,
        notices=notices,
    )
