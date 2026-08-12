import json
import threading
import time

from app.local_runtime import (
    LOCAL_MODEL_MAX_CHARACTERS,
    local_mistral_ready,
    local_model_eligible,
    preflight_local_mistral,
)


def test_local_model_eligibility_is_explicit_at_size_boundary() -> None:
    assert local_model_eligible("x" * LOCAL_MODEL_MAX_CHARACTERS, True)
    assert not local_model_eligible("x" * (LOCAL_MODEL_MAX_CHARACTERS + 1), True)
    assert not local_model_eligible("short", False)


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


def test_readiness_has_a_hard_deadline_when_local_runtime_drips_or_stalls(monkeypatch) -> None:
    closed = threading.Event()

    class SlowResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.close()

        def read(self, limit):
            closed.wait(2)
            return b'{"models": [{"name": "mistral"}]}'

        def close(self):
            closed.set()

    class Opener:
        def open(self, url, timeout):
            return SlowResponse()

    monkeypatch.setattr("urllib.request.build_opener", lambda *handlers: Opener())
    started = time.monotonic()

    assert local_mistral_ready(timeout=0.05) is False
    assert time.monotonic() - started < 0.5
    assert closed.wait(0.5)


def test_readiness_closes_a_response_that_arrives_just_after_its_deadline(monkeypatch) -> None:
    release_open = threading.Event()
    response_returned = threading.Event()
    closed = threading.Event()

    class LateResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.close()

        def read(self, limit):
            closed.wait(2)
            return b'{"models": [{"name": "mistral"}]}'

        def close(self):
            closed.set()

    class Opener:
        def open(self, url, timeout):
            release_open.wait(1)
            response_returned.set()
            return LateResponse()

    monkeypatch.setattr("urllib.request.build_opener", lambda *handlers: Opener())
    threading.Timer(0.08, release_open.set).start()
    started = time.monotonic()

    assert local_mistral_ready(timeout=0.05) is False
    assert time.monotonic() - started < 0.5
    assert response_returned.wait(0.5)
    assert closed.wait(0.5)


def test_preflight_uses_short_hard_local_readiness_check(monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(
        "app.local_runtime.local_mistral_ready",
        lambda *, timeout: calls.append(timeout) or True,
    )

    assert preflight_local_mistral() is True
    assert calls == [0.5]
