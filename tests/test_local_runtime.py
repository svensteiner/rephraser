import json

from app.local_runtime import local_mistral_ready


def test_readiness_refuses_spoofed_loopback_without_network(monkeypatch) -> None:
    called = False

    def forbidden_open(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("network must not be touched")

    monkeypatch.setenv("MISTRAL_BASE_URL", "http://localhost.evil.example:11434")
    monkeypatch.setattr("urllib.request.OpenerDirector.open", forbidden_open)
    assert local_mistral_ready() is False
    assert called is False


def test_readiness_recognizes_configured_local_model(monkeypatch) -> None:
    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def read(self, limit):
            assert limit == 1_000_001
            return json.dumps({"models": [{"name": "mistral:latest"}]}).encode()

    class Opener:
        def open(self, url, timeout):
            assert url == "http://127.0.0.1:11434/api/tags"
            assert timeout == 0.1
            return Response()

    monkeypatch.setenv("MISTRAL_BASE_URL", "http://127.0.0.1:11434")
    monkeypatch.setenv("MISTRAL_MODEL", "mistral:latest")
    monkeypatch.setattr("urllib.request.build_opener", lambda *handlers: Opener())
    assert local_mistral_ready(timeout=0.1) is True


def test_readiness_rejects_oversized_local_response(monkeypatch) -> None:
    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def read(self, limit):
            return b"x" * limit

    class Opener:
        def open(self, url, timeout):
            return Response()

    monkeypatch.setattr("urllib.request.build_opener", lambda *handlers: Opener())
    assert local_mistral_ready() is False
