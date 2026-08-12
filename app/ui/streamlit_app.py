from __future__ import annotations

import json

import streamlit as st
import streamlit.components.v2 as components

from app.local_runtime import (
    LOCAL_MODEL_MAX_CHARACTERS,
    local_mistral_ready,
    local_model_eligible,
    preflight_local_mistral,
)
from app.models import TransformOptions, ValidationWarning
from app.protection import missing_protected_terms, normalize_protected_terms
from app.pipeline import run_pipeline
from app.providers.base import ProviderError
from app.ui_state import ResultState, classify_result_state, result_actions_allowed

MAX_CHARACTERS = 2_000_000


@st.cache_data(ttl=10, show_spinner=False)
def cached_local_mistral_ready() -> bool:
    return local_mistral_ready()


copy_text_component = components.component(
    "copy_text_button",
    html='<button id="copy">Ergebnis kopieren</button><span id="status"></span>',
    css="""
      #copy {background:#176b4d;color:white;border:0;border-radius:8px;padding:11px 22px;
             font:600 16px system-ui;cursor:pointer}
      #status {margin-left:12px;font:14px system-ui;color:#315b49}
    """,
    js="""
      export default function({data, parentElement}) {
        const button = parentElement.querySelector('#copy');
        const status = parentElement.querySelector('#status');
        const copy = async () => {
          try {
            await navigator.clipboard.writeText(data.text);
            status.textContent = 'Kopiert ✓';
          } catch (_) {
            status.textContent = 'Bitte Text markieren und Strg+C drücken.';
          }
        };
        button.addEventListener('click', copy);
        return () => button.removeEventListener('click', copy);
      }
    """,
)

st.set_page_config(page_title="Text verbessern", page_icon="✍️", layout="centered")
st.markdown(
    """
    <style>
      .block-container {max-width: 920px; padding-top: 2.2rem;}
      [data-testid="stHeader"], #MainMenu, footer {display:none;}
      [data-testid="stTextArea"] textarea {font-size: 1rem; line-height: 1.55;}
      .privacy-note {color: #557064; font-size: .92rem; margin-top: -.35rem;}
      .result-label {font-size: 1.45rem; font-weight: 650; margin-top: 1rem;}
      div.stButton > button[kind="primary"] {min-height: 3.2rem; font-size: 1.05rem; font-weight: 650;}
    </style>
    """,
    unsafe_allow_html=True,
)


def copy_button(text: str) -> None:
    copy_text_component(key="copy-result", data={"text": text}, height=54)


if "source_text" not in st.session_state:
    st.session_state.source_text = ""
if "result" not in st.session_state:
    st.session_state.result = None
if "result_source" not in st.session_state:
    st.session_state.result_source = ""

st.title("Text verbessern")
st.markdown(
    "Text aus Claude oder einer anderen Quelle einfügen. "
    "Die Bearbeitung läuft lokal auf diesem PC."
)

mistral_ready = cached_local_mistral_ready()
if mistral_ready:
    st.success("Sofortige Textverbesserung bereit; Mistral ist zusätzlich verfügbar.", icon="✅")
else:
    st.info(
        "Sofortige lokale Textverbesserung bereit. Die optionale Mistral-Variante ist nicht verfügbar.",
        icon="ℹ️",
    )

with st.expander("Text aus einer Datei öffnen"):
    uploaded = st.file_uploader("TXT- oder Markdown-Datei", type=["txt", "md"], label_visibility="collapsed")
    if uploaded is not None and uploaded.file_id != st.session_state.get("loaded_file_id"):
        try:
            st.session_state.source_text = uploaded.getvalue().decode("utf-8-sig")
            st.session_state.loaded_file_id = uploaded.file_id
            st.session_state.result = None
        except UnicodeDecodeError:
            st.error("Die Datei ist nicht als UTF-8 lesbar. Bitte den Inhalt direkt einfügen.")

st.text_area(
    "Dein Text",
    key="source_text",
    height=250,
    placeholder="Text hier einfügen …",
    max_chars=MAX_CHARACTERS,
)
word_count = len(st.session_state.source_text.split())
st.caption(f"{word_count:,} Wörter · {len(st.session_state.source_text):,} Zeichen".replace(",", "."))

with st.expander("Bearbeitung anpassen"):
    mistral_for_text = local_model_eligible(st.session_state.source_text, mistral_ready)
    mode_choices = (
        ["Schnell verbessern (empfohlen)", "Nur Format bereinigen", "Gründlich mit Mistral (bis 45 s)"]
        if mistral_for_text
        else ["Schnell verbessern (empfohlen)", "Nur Format bereinigen"]
    )
    mode_label = st.radio(
        "Bearbeitung",
        mode_choices,
        horizontal=True,
    )
    if mistral_ready and not mistral_for_text and len(st.session_state.source_text) > LOCAL_MODEL_MAX_CHARACTERS:
        st.caption(
            f"Für Texte über {LOCAL_MODEL_MAX_CHARACTERS:,} Zeichen ist die schnelle lokale Bearbeitung aktiv. "
            "Der vollständige Text bleibt erhalten.".replace(",", ".")
        )
    language_label = st.selectbox("Sprache", ["Automatisch erkennen", "Deutsch", "Englisch"])
    if mistral_ready and mode_label == "Gründlich mit Mistral (bis 45 s)":
        tone_label = st.selectbox(
            "Stil",
            ["Stil beibehalten", "Professionell", "Analytisch", "Kompakt", "Akademisch", "LinkedIn / Artikel"],
        )
        custom_style = st.text_input("Eigene Stilvorgabe (optional)", placeholder="z. B. sachlich, kurze Absätze")
    else:
        tone_label = "Stil beibehalten"
        custom_style = ""
        st.caption("Stiloptionen gelten nur für die optionale gründliche Mistral-Bearbeitung.")
    st.markdown("**Unverändert schützen**")
    protection_columns = st.columns(3)
    preserve_numbers = protection_columns[0].checkbox("Zahlen und Daten", value=True)
    preserve_citations = protection_columns[1].checkbox("Quellen und Links", value=True)
    preserve_quotations = protection_columns[2].checkbox("Wörtliche Zitate", value=True)
    st.caption("Eigennamen und Tatsachenbehauptungen werden unabhängig davon immer geprüft.")
    protected_terms_text = st.text_area(
        "Eigene Begriffe exakt schützen (optional)",
        placeholder="Ein Begriff pro Zeile, z. B. UniCredit BulBank",
        height=90,
        max_chars=5_000,
    )
    protection_error = ""
    try:
        protected_terms = normalize_protected_terms(protected_terms_text.splitlines())
    except ValueError as error:
        protected_terms = []
        protection_error = str(error)
    if not protection_error:
        missing_terms = missing_protected_terms(st.session_state.source_text, protected_terms)
        if missing_terms:
            protection_error = "Nicht exakt im Ausgangstext gefunden: " + ", ".join(missing_terms[:5])
    if protection_error:
        st.warning(protection_error)

tone_map = {
    "Stil beibehalten": "professional", "Professionell": "professional",
    "Analytisch": "analytical", "Kompakt": "concise", "Akademisch": "academic",
    "LinkedIn / Artikel": "LinkedIn/article",
}
language_map = {
    "Automatisch erkennen": "auto-detect",
    "Deutsch": "German",
    "Englisch": "English",
}

action_label = "Text verbessern"
run = st.button(action_label, type="primary", use_container_width=True,
                disabled=not st.session_state.source_text.strip() or bool(protection_error))
if run:
    requested_thorough_mode = mode_label == "Gründlich mit Mistral (bis 45 s)" and mistral_ready
    mistral_preflight_failed = False
    if requested_thorough_mode:
        with st.spinner("Lokales Mistral wird kurz geprüft …"):
            mistral_preflight_failed = not preflight_local_mistral()
        if mistral_preflight_failed:
            # The cached banner may be up to ten seconds old.  The next rerun must
            # accurately hide the thorough mode; no pasted text was sent here.
            cached_local_mistral_ready.clear()
    if mode_label == "Nur Format bereinigen":
        provider, strength = "rules", "light"
    elif requested_thorough_mode and not mistral_preflight_failed:
        provider = "rules+mistral-local"
        strength = "substantial"
    elif mistral_preflight_failed:
        provider, strength = "rules", "light"
    else:
        provider, strength = "fast-editor", "medium"
    options = TransformOptions(
        provider=provider,
        rewrite_strength=strength,
        tone=tone_map[tone_label],
        language=language_map[language_label],
        preserve_citations=preserve_citations,
        preserve_numbers=preserve_numbers,
        preserve_quotations=preserve_quotations,
        custom_author_style=custom_style,
        protected_terms=protected_terms,
    )
    message = (
        "Gründliche lokale Mistral-Überarbeitung läuft – höchstens 45 Sekunden."
        if "mistral" in provider
        else "Mistral derzeit nicht erreichbar – sichere lokale Fassung wird sofort erstellt."
        if mistral_preflight_failed
        else "Text wird sofort lokal verbessert."
    )
    with st.spinner(message):
        try:
            st.session_state.result = run_pipeline(st.session_state.source_text, options)
            if mistral_preflight_failed:
                st.session_state.result.audit.requested_provider = "rules+mistral-local"
                # Keep the applied safe-pass settings intact and expose the original
                # thorough choice separately for a truthful audit trail.
                st.session_state.result.audit.options["requested_provider"] = "rules+mistral-local"
                st.session_state.result.audit.options["requested_rewrite_strength"] = "substantial"
                st.session_state.result.audit.options["fallback_reason"] = "provider_unavailable"
                st.session_state.result.audit.fact_preservation_warnings.append(ValidationWarning(
                    kind="provider_unavailable",
                    severity="medium",
                    value="streamlit_mistral_preflight",
                    message=("Das lokale Mistral war vor der Bearbeitung nicht erreichbar; "
                             "ausgegeben wurde die sichere lokale Grundbereinigung."),
                ))
            st.session_state.result_source = st.session_state.source_text
            st.session_state.original_preview = st.session_state.source_text
            st.session_state.editable_result = st.session_state.result.rewritten_text
            was_rejected = any(
                warning.kind == "rewrite_rejected"
                for warning in st.session_state.result.audit.fact_preservation_warnings
            )
            provider_fallback = any(
                warning.kind in {"provider_unavailable", "provider_timeout", "model_input_too_long"}
                for warning in st.session_state.result.audit.fact_preservation_warnings
            )
            if any(
                warning.kind == "model_input_too_long"
                for warning in st.session_state.result.audit.fact_preservation_warnings
            ):
                st.session_state.processing_note = "Text war für Mistral zu lang; vollständig lokal schnell bearbeitet."
            elif provider_fallback:
                st.session_state.processing_note = "Mistral war nicht verfügbar; sichere lokale Grundbereinigung angezeigt."
            elif was_rejected:
                st.session_state.processing_note = "Lokal sicher bereinigt; die Modellfassung wurde verworfen."
            elif st.session_state.result.rewritten_text == st.session_state.source_text:
                st.session_state.processing_note = "Keine sichere Verbesserung erforderlich – Text unverändert."
            elif "mistral" in provider:
                st.session_state.processing_note = "Lokal mit Regeln und Mistral verarbeitet."
            elif provider == "fast-editor":
                st.session_state.processing_note = "Sofort und vollständig lokal verbessert."
            else:
                st.session_state.processing_note = "Lokal mit sicheren Regeln bereinigt. Das Sprachmodell war nicht aktiv."
        except ProviderError as error:
            st.session_state.result = None
            st.error("Das lokale Sprachmodell antwortet gerade nicht. Dein Text hat diesen PC nicht verlassen.")
            with st.expander("Technische Information"):
                st.code(str(error))

result = st.session_state.result
if result is not None:
    displayed_result = st.session_state.get("editable_result", result.rewritten_text)
    result_state = classify_result_state(
        st.session_state.source_text,
        st.session_state.result_source,
        result.rewritten_text,
        displayed_result,
    )
    if result_state == ResultState.STALE:
        st.warning("Der Ausgangstext wurde geändert. Bitte erneut überarbeiten.")
    st.markdown('<div class="result-label">Fertiger Text</div>', unsafe_allow_html=True)
    st.caption(st.session_state.processing_note)
    comparison = st.columns(2)
    with comparison[0]:
        st.text_area("Original", height=350, key="original_preview", disabled=True)
    with comparison[1]:
        st.text_area("Bearbeitetes Ergebnis", height=350, key="editable_result")
    result_state = classify_result_state(
        st.session_state.source_text,
        st.session_state.result_source,
        result.rewritten_text,
        st.session_state.editable_result,
    )
    if result_actions_allowed(result_state):
        copy_button(st.session_state.editable_result)

    warning_count = len(result.audit.fact_preservation_warnings)
    warning_kinds = {warning.kind for warning in result.audit.fact_preservation_warnings}
    if result_state == ResultState.MANUALLY_EDITED:
        st.info("Ergebnis manuell geändert – die automatische Prüfung gilt für diese Fassung nicht mehr.")
    elif result_state == ResultState.STALE:
        st.info("Das angezeigte Ergebnis gehört zum vorherigen Ausgangstext und kann nicht gespeichert werden.")
    elif "model_input_too_long" in warning_kinds:
        st.info("Der Text war für einen Modelldurchlauf zu lang. Die vollständige sichere Fassung wird angezeigt.")
    elif "provider_timeout" in warning_kinds:
        st.warning("Mistral hat die Zeitgrenze erreicht. Das sicher bereinigte Ergebnis wird angezeigt.")
    elif "provider_unavailable" in warning_kinds:
        st.warning("Mistral war nicht verfügbar. Die sichere lokale Grundbereinigung wird angezeigt.")
    elif "rewrite_rejected" in warning_kinds:
        st.warning("Die sprachliche Fassung wurde vorsichtshalber verworfen. Der sicher bereinigte Text wird angezeigt.")
    elif warning_count:
        st.warning(f"Bitte kurz prüfen: {warning_count} mögliche Abweichung(en) wurden gefunden.")
    elif not result.audit.transformations:
        st.info("Der Text ist unverändert; es wurde keine sichere Verbesserung benötigt oder gefunden.")
    else:
        st.success("Keine auffälligen Änderungen an Zahlen, Daten, Namen, Zitaten oder Links gefunden.")

    if result_actions_allowed(result_state):
        download_text = st.session_state.editable_result
        downloads = st.columns(2)
        downloads[0].download_button("Als TXT speichern", download_text, "bearbeiteter-text.txt", "text/plain",
                                     use_container_width=True)
        downloads[1].download_button("Als Markdown speichern", download_text, "bearbeiteter-text.md", "text/markdown",
                                     use_container_width=True)

    with st.expander("Änderungen und Prüfung"):
        if result_state != ResultState.CURRENT:
            st.info(
                "Prüfdetails sind nur für das unveränderte, automatisch erzeugte Ergebnis verfügbar. "
                "Bitte erneut überarbeiten, um einen aktuellen Prüfbericht zu erstellen."
            )
        elif result.audit.fact_preservation_warnings:
            st.subheader("Prüfhinweise")
            for warning in result.audit.fact_preservation_warnings:
                st.warning(f"{warning.message} Wert: {warning.value}")
        if result_state == ResultState.CURRENT:
            st.subheader("Änderungen")
            st.caption(
                f"Wortlaut verändert: {result.audit.diff.surface_diversity:.0%} "
                "(Oberflächenvergleich; keine Aussage über semantische Gleichheit)."
            )
            st.code("\n".join(result.audit.diff.sentence_diff) or "Keine Änderungen", language="diff", wrap_lines=True)
            st.subheader("Qualität vor und nach der Bearbeitung")
            before = result.audit.quality_metrics_before
            after = result.audit.quality_metrics_after
            st.table([
            {"Kennzahl": "Sätze", "Vorher": before.sentence_count, "Nachher": after.sentence_count},
            {"Kennzahl": "Ø Satzlänge", "Vorher": before.sentence_length_mean,
             "Nachher": after.sentence_length_mean},
            {"Kennzahl": "Lexikalische Vielfalt", "Vorher": before.lexical_diversity,
             "Nachher": after.lexical_diversity},
            {"Kennzahl": "Wiederholte Wörter", "Vorher": before.repeated_word_count,
             "Nachher": after.repeated_word_count},
            {"Kennzahl": "Füllphrasen", "Vorher": before.filler_phrase_count,
             "Nachher": after.filler_phrase_count},
            {"Kennzahl": "Passiv-Indikatoren", "Vorher": before.passive_voice_indicators,
             "Nachher": after.passive_voice_indicators},
            {"Kennzahl": "Lesbarkeitsindikator", "Vorher": before.readability,
             "Nachher": after.readability},
            ])
            unusual = result.audit.inspection.characters
            if unusual:
                st.subheader("Ungewöhnliche Zeichen")
                st.write(
                    f"{len(unusual)} Vorkommen in {len(result.audit.inspection.character_summary)} "
                    "Zeichentyp(en) erkannt. Unbekannte Muster wurden beibehalten."
                )
            audit_json = json.dumps(result.audit.model_dump(mode="json"), ensure_ascii=False, indent=2)
            st.download_button("Prüfbericht herunterladen", audit_json, "pruefbericht.json", "application/json")

    if st.button("Neuen Text bearbeiten"):
        st.session_state.source_text = ""
        st.session_state.result = None
        st.session_state.result_source = ""
        st.session_state.pop("original_preview", None)
        st.session_state.pop("editable_result", None)
        st.rerun()

st.divider()
st.markdown(
    '<div class="privacy-note">Dieses Werkzeug verbessert Formatierung und Stil. Es bewertet keine '
    'KI-Herkunft und umgeht keine Provenienz- oder Watermarking-Systeme. Eingefügte Texte werden '
    'nicht in GitHub gespeichert.</div>',
    unsafe_allow_html=True,
)
