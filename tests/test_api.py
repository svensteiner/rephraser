from fastapi.testclient import TestClient

from app.main import app


def test_transform_endpoint() -> None:
    response = TestClient(app).post("/transform", json={"text": "Grüße\u00a0aus Wien."})
    assert response.status_code == 200
    assert response.json()["rewritten_text"] == "Grüße aus Wien."
