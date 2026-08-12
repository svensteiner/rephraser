from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading

import streamlit as st
from streamlit.testing.v1 import AppTest


UI = Path(__file__).parents[1] / "app" / "ui" / "streamlit_app.py"


def test_simple_rule_based_paste_workflow() -> None:
    app = AppTest.from_file(str(UI), default_timeout=30).run()
    assert not list(app.exception)
    assert app.title[0].value == "Text verbessern"
    assert [button.label for button in app.button] == ["Text verbessern"]
    assert [checkbox.label for checkbox in app.checkbox] == [
        "Zahlen und Daten",
        "Quellen und Links",
        "Wörtliche Zitate",
    ]

    app.radio[0].set_value("Nur Format bereinigen")
    app.text_area(key="source_text").input("Grüße\u00a0aus Wien.")
    app.button[0].click().run()

    assert not list(app.exception)
    assert app.text_area(key="original_preview").value == "Grüße\u00a0aus Wien."
    assert app.text_area(key="editable_result").value == "Grüße aus Wien."


def test_default_ui_path_improves_business_text_immediately() -> None:
    app = AppTest.from_file(str(UI), default_timeout=30).run()
    app.text_area(key="source_text").input("We would like to better understand the accounts.")
    app.button[0].click().run()
    assert not list(app.exception)
    assert app.text_area(key="editable_result").value == "We would appreciate clarification on the accounts."
    assert any(item.value == "Qualität vor und nach der Bearbeitung" for item in app.subheader)


def test_ui_can_protect_an_exact_business_term() -> None:
    app = AppTest.from_file(str(UI), default_timeout=30).run()
    source = "We would like to better understand Project Aurora. In order to proceed, we need details."
    app.text_area(key="source_text").input(source).run()
    protection = next(area for area in app.text_area if area.label == "Eigene Begriffe exakt schützen (optional)")
    protection.input("We would like to better understand").run()
    app.button[0].click().run()
    assert not list(app.exception)
    assert app.text_area(key="editable_result").value.startswith("We would like to better understand")
    assert "To proceed" in app.text_area(key="editable_result").value


def test_ui_blocks_a_protected_term_not_found_in_source() -> None:
    app = AppTest.from_file(str(UI), default_timeout=30).run()
    app.text_area(key="source_text").input("Project Aurora ist aktiv.").run()
    protection = next(area for area in app.text_area if area.label == "Eigene Begriffe exakt schützen (optional)")
    protection.input("Project Borealis").run()
    assert app.button[0].disabled is True
    assert any("Nicht exakt im Ausgangstext gefunden" in item.value for item in app.warning)


def test_changed_source_makes_old_result_non_actionable() -> None:
    app = AppTest.from_file(str(UI), default_timeout=30).run()
    app.text_area(key="source_text").input("We would like to better understand the accounts.")
    app.button[0].click().run()
    app.text_area(key="source_text").input("A different source.").run()
    assert any("vorherigen Ausgangstext" in item.value for item in app.info)
    assert not list(app.download_button)


def test_manual_result_edit_disables_stale_audit_but_keeps_text_downloads() -> None:
    app = AppTest.from_file(str(UI), default_timeout=30).run()
    app.text_area(key="source_text").input("We would like to better understand the accounts.")
    app.button[0].click().run()
    app.text_area(key="editable_result").input("Manually edited result.").run()
    assert any("manuell geändert" in item.value for item in app.info)
    assert len(app.download_button) == 2
    assert all(button.label != "Prüfbericht herunterladen" for button in app.download_button)


def test_thorough_streamlit_mode_rechecks_stale_local_model_status_before_text_is_sent(monkeypatch) -> None:
    state = {"available": True, "calls": 0, "post_called": False}

    class TagsHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            assert self.path == "/api/tags"
            state["calls"] += 1
            models = [{"name": "mistral:latest"}] if state["available"] else []
            body = json.dumps({"models": models}).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            state["post_called"] = True
            self.send_error(500)

        def log_message(self, format, *args):
            return None

    server = ThreadingHTTPServer(("127.0.0.1", 0), TagsHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setenv("MISTRAL_BASE_URL", f"http://127.0.0.1:{server.server_port}")
    monkeypatch.setenv("MISTRAL_MODEL", "mistral:latest")
    st.cache_data.clear()
    try:
        app = AppTest.from_file(str(UI), default_timeout=30).run()
        app.text_area(key="source_text").input("Ein klarer Text.").run()
        app.radio[0].set_value("Gründlich mit Mistral (bis 45 s)").run()
        state["available"] = False

        app.button[0].click().run()

        assert app.text_area(key="editable_result").value == "Ein klarer Text."
        assert state["calls"] >= 2
        assert state["post_called"] is False
        assert any("Mistral war nicht verfügbar" in item.value for item in app.caption)
    finally:
        server.shutdown()
        server.server_close()
        st.cache_data.clear()
