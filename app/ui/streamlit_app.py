from __future__ import annotations

import json
import os
import urllib.request

import streamlit as st
import streamlit.components.v2 as components

from app.models import TransformOptions
from app.pipeline import run_pipeline
from app.providers.base import ProviderError

MAX_CHARACTERS = 2_000_000

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


@st.cache_data(ttl=10, show_spinner=False)
def local_mistral_ready() -> bool:
    base_url = os.getenv("MISTRAL_BASE_URL", "http://127.0.0.1:11434").rstrip("/")
    model = os.getenv("MISTRAL_MODEL", "mistral").split(":", 1)[0]
    try:
        with urllib.request.urlopen(base_url + "/api/tags", timeout=0.8) as response:
            data = json.load(response)
        return any(item.get("name", "").split(":", 1)[0] == model for item in data.get("models", []))
    except (OSError, ValueError, KeyError):
        return False


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

mistral_ready = local_mistral_ready()
if mistral_ready:
    st.success("Lokal bereit – sichere Bereinigung und sprachliche Überarbeitung verfügbar.", icon="✅")
else:
    st.info("Lokal bereit – derzeit ist nur die sichere Grundbereinigung verfügbar.", icon="ℹ️")

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
    mode_label = st.radio(
        "Bearbeitung",
        ["Automatisch (empfohlen)", "Nur sichere Bereinigung", "Deutlich umformulieren"],
        horizontal=True,
    )
    tone_label = st.selectbox(
        "Stil",
        ["Stil beibehalten", "Professionell", "Analytisch", "Kompakt", "Akademisch", "LinkedIn / Artikel"],
    )
    custom_style = st.text_input("Eigene Stilvorgabe (optional)", placeholder="z. B. sachlich, kurze Absätze")

tone_map = {
    "Stil beibehalten": "professional", "Professionell": "professional",
    "Analytisch": "analytical", "Kompakt": "concise", "Akademisch": "academic",
    "LinkedIn / Artikel": "LinkedIn/article",
}

run = st.button("Text überarbeiten", type="primary", use_container_width=True,
                disabled=not st.session_state.source_text.strip())
if run:
    if mode_label == "Nur sichere Bereinigung":
        provider, strength = "rules", "light"
    elif mistral_ready:
        provider = "rules+mistral-local"
        strength = "substantial" if mode_label == "Deutlich umformulieren" else "medium"
    else:
        provider, strength = "rules", "light"
    options = TransformOptions(
        provider=provider,
        rewrite_strength=strength,
        tone=tone_map[tone_label],
        language="auto-detect",
        preserve_citations=True,
        preserve_numbers=True,
        preserve_quotations=True,
        custom_author_style=custom_style,
    )
    message = "Lokale Überarbeitung läuft – der erste Durchlauf kann etwa eine Minute dauern."
    with st.spinner(message):
        try:
            st.session_state.result = run_pipeline(st.session_state.source_text, options)
            st.session_state.result_source = st.session_state.source_text
            st.session_state.editable_result = st.session_state.result.rewritten_text
            was_rejected = any(
                warning.kind == "rewrite_rejected"
                for warning in st.session_state.result.audit.fact_preservation_warnings
            )
            if was_rejected:
                st.session_state.processing_note = "Lokal sicher bereinigt; die Modellfassung wurde verworfen."
            elif "mistral" in provider:
                st.session_state.processing_note = "Lokal mit Regeln und Mistral verarbeitet."
            else:
                st.session_state.processing_note = "Lokal mit sicheren Regeln bereinigt. Das Sprachmodell war nicht aktiv."
        except ProviderError as error:
            st.session_state.result = None
            st.error("Das lokale Sprachmodell antwortet gerade nicht. Dein Text wurde nicht gesendet.")
            with st.expander("Technische Information"):
                st.code(str(error))

result = st.session_state.result
if result is not None:
    if st.session_state.result_source != st.session_state.source_text:
        st.warning("Der Ausgangstext wurde geändert. Bitte erneut überarbeiten.")
    st.markdown('<div class="result-label">Fertiger Text</div>', unsafe_allow_html=True)
    st.caption(st.session_state.processing_note)
    st.text_area("Bearbeitetes Ergebnis", height=350, key="editable_result",
                 label_visibility="collapsed")
    copy_button(st.session_state.editable_result)

    warning_count = len(result.audit.fact_preservation_warnings)
    rejected = any(warning.kind == "rewrite_rejected" for warning in result.audit.fact_preservation_warnings)
    if rejected:
        st.warning("Die sprachliche Fassung wurde vorsichtshalber verworfen. Der sicher bereinigte Text wird angezeigt.")
    elif warning_count:
        st.warning(f"Bitte kurz prüfen: {warning_count} mögliche Abweichung(en) wurden gefunden.")
    else:
        st.success("Keine auffälligen Änderungen an Zahlen, Daten, Namen, Zitaten oder Links gefunden.")

    download_text = st.session_state.editable_result
    downloads = st.columns(2)
    downloads[0].download_button("Als TXT speichern", download_text, "bearbeiteter-text.txt", "text/plain",
                                 use_container_width=True)
    downloads[1].download_button("Als Markdown speichern", download_text, "bearbeiteter-text.md", "text/markdown",
                                 use_container_width=True)

    with st.expander("Änderungen und Prüfung"):
        if result.audit.fact_preservation_warnings:
            st.subheader("Prüfhinweise")
            for warning in result.audit.fact_preservation_warnings:
                st.warning(f"{warning.message} Wert: {warning.value}")
        st.subheader("Änderungen")
        st.code("\n".join(result.audit.diff.sentence_diff) or "Keine Änderungen", language="diff", wrap_lines=True)
        unusual = result.audit.inspection.characters
        if unusual:
            st.subheader("Ungewöhnliche Zeichen")
            st.write(f"{len(unusual)} Zeichen wurden erkannt. Unbekannte Muster wurden beibehalten.")
        audit_json = json.dumps(result.audit.model_dump(mode="json"), ensure_ascii=False, indent=2)
        st.download_button("Prüfbericht herunterladen", audit_json, "pruefbericht.json", "application/json")

    if st.button("Neuen Text bearbeiten"):
        st.session_state.source_text = ""
        st.session_state.result = None
        st.session_state.result_source = ""
        st.session_state.pop("editable_result", None)
        st.rerun()

st.divider()
st.markdown(
    '<div class="privacy-note">Dieses Werkzeug verbessert Formatierung und Stil. Es bewertet keine '
    'KI-Herkunft und umgeht keine Provenienz- oder Watermarking-Systeme. Eingefügte Texte werden '
    'nicht in GitHub gespeichert.</div>',
    unsafe_allow_html=True,
)
