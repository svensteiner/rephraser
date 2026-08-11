from pathlib import Path

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
