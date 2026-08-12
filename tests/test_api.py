from fastapi.testclient import TestClient

from app.main import app


def test_transform_endpoint() -> None:
    response = TestClient(app).post("/transform", json={"text": "Grüße\u00a0aus Wien."})
    assert response.status_code == 200
    assert response.json()["rewritten_text"] == "Grüße aus Wien."


def test_transform_endpoint_uses_instant_editor_by_default() -> None:
    response = TestClient(app).post(
        "/transform",
        json={"text": "We would like to better understand the accounts."},
    )
    assert response.status_code == 200
    assert response.json()["rewritten_text"] == "We would appreciate clarification on the accounts."


def test_transform_endpoint_honours_explicit_protected_terms() -> None:
    response = TestClient(app).post(
        "/transform",
        json={
            "text": "We would like to better understand Project Aurora. In order to proceed, reply.",
            "options": {"protected_terms": ["We would like to better understand"]},
        },
    )
    assert response.status_code == 200
    assert response.json()["rewritten_text"].startswith("We would like to better understand")
    assert response.json()["audit"]["semantic_constraints"]["protected_terms"] == [
        "We would like to better understand"
    ]


def test_transform_endpoint_rejects_invisible_protected_term() -> None:
    response = TestClient(app).post(
        "/transform",
        json={"text": "Project Aurora", "options": {"protected_terms": ["Project\u200bAurora"]}},
    )
    assert response.status_code == 422
