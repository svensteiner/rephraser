import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading
import time

import pytest

from app.models import TransformOptions
from app.providers.base import ProviderError
from app.providers.mistral_provider import LocalMistralProvider
from app.semantic import extract_semantics


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost.evil.com:11434",
        "https://localhost:11434",
        "http://example.org:11434",
        "http://user@localhost:11434",
        "http://localhost:11434/ollama",
        "http://localhost:11434?target=remote",
        "http://localhost",
        "http://localhost:0",
        "http://localhost:not-a-port",
    ],
)
def test_mistral_rejects_non_local_or_tls_urls(url: str) -> None:
    with pytest.raises(ProviderError):
        LocalMistralProvider(base_url=url)


@pytest.mark.parametrize("url", ["http://localhost:11434", "http://127.0.0.1:11434", "http://[::1]:11434"])
def test_mistral_accepts_loopback(url: str) -> None:
    expected = "http://127.0.0.1:11434" if "localhost" in url else url
    assert LocalMistralProvider(base_url=url).base_url == expected


def test_mistral_requests_reproducible_local_generation(monkeypatch) -> None:
    captured = {}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def read(self, limit):
            return b'{"response": "Ein klarer Satz."}'

    class Opener:
        def open(self, request, timeout):
            assert timeout == 42
            captured.update(json.loads(request.data))
            return Response()

    monkeypatch.setattr("urllib.request.build_opener", lambda *handlers: Opener())
    text = "Ein klarer Satz."
    result = LocalMistralProvider().rewrite(text, extract_semantics(text), TransformOptions())
    assert result == text
    assert captured["options"] == {"temperature": 0, "seed": 42, "num_predict": 96}
    assert captured["stream"] is False


def test_mistral_exact_value_options_control_the_mandatory_prompt(monkeypatch) -> None:
    captured = {}
    text = 'Anna Müller meldete am 3. März 2026 12,5 %. „Bestätigt.“ https://example.org/x'

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def read(self, limit):
            return json.dumps({"response": text}).encode("utf-8")

    class Opener:
        def open(self, request, timeout):
            captured.update(json.loads(request.data))
            return Response()

    monkeypatch.setattr("urllib.request.build_opener", lambda *handlers: Opener())
    options = TransformOptions(
        preserve_numbers=False,
        preserve_citations=False,
        preserve_quotations=False,
    )
    LocalMistralProvider().rewrite(text, extract_semantics(text), options)
    mandatory_json = captured["prompt"].split("Mandatory exact strings: ", 1)[1].splitlines()[0]
    assert json.loads(mandatory_json) == ["Anna Müller"]


def test_mistral_prompt_includes_explicit_protected_terms(monkeypatch) -> None:
    captured = {}
    text = "Project Aurora bleibt unverändert."

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def read(self, limit):
            return json.dumps({"response": text}).encode("utf-8")

    class Opener:
        def open(self, request, timeout):
            captured.update(json.loads(request.data))
            return Response()

    monkeypatch.setattr("urllib.request.build_opener", lambda *handlers: Opener())
    options = TransformOptions(protected_terms=["Project Aurora"])
    LocalMistralProvider().rewrite(text, extract_semantics(text, options.protected_terms), options)
    mandatory_json = captured["prompt"].split("Mandatory exact strings: ", 1)[1].splitlines()[0]
    assert "Project Aurora" in json.loads(mandatory_json)


def test_mistral_enforces_wall_clock_deadline_and_closes_slow_response(monkeypatch) -> None:
    closed = threading.Event()

    class SlowResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.close()

        def read(self, limit):
            closed.wait(2)
            return b'{"response": "too late"}'

        def close(self):
            closed.set()

    class Opener:
        def open(self, request, timeout):
            return SlowResponse()

    monkeypatch.setattr("urllib.request.build_opener", lambda *handlers: Opener())
    provider = LocalMistralProvider()
    provider.timeout = 0.05
    started = time.monotonic()
    with pytest.raises(ProviderError, match="total deadline") as captured_error:
        provider.rewrite("Ein Satz.", extract_semantics("Ein Satz."), TransformOptions())
    assert captured_error.value.code == "provider_timeout"
    assert time.monotonic() - started < 0.5
    assert closed.wait(0.5)


def test_mistral_deadline_covers_connection_or_header_stall(monkeypatch) -> None:
    class BlockingOpener:
        def open(self, request, timeout):
            time.sleep(1)

    monkeypatch.setattr("urllib.request.build_opener", lambda *handlers: BlockingOpener())
    provider = LocalMistralProvider()
    provider.timeout = 0.05
    started = time.monotonic()

    with pytest.raises(ProviderError) as captured_error:
        provider.rewrite("Ein Satz.", extract_semantics("Ein Satz."), TransformOptions())

    assert captured_error.value.code == "provider_timeout"
    assert time.monotonic() - started < 0.5


def test_mistral_closes_a_response_that_arrives_just_after_deadline(monkeypatch) -> None:
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
            return b'{"response": "too late"}'

        def close(self):
            closed.set()

    class Opener:
        def open(self, request, timeout):
            release_open.wait(1)
            response_returned.set()
            return LateResponse()

    monkeypatch.setattr("urllib.request.build_opener", lambda *handlers: Opener())
    provider = LocalMistralProvider()
    provider.timeout = 0.05
    threading.Timer(0.08, release_open.set).start()
    started = time.monotonic()

    with pytest.raises(ProviderError) as captured_error:
        provider.rewrite("Ein Satz.", extract_semantics("Ein Satz."), TransformOptions())

    assert captured_error.value.code == "provider_timeout"
    assert time.monotonic() - started < 0.5
    assert response_returned.wait(0.5)
    assert closed.wait(0.5)


def test_mistral_deadline_stops_a_real_slow_drip_response() -> None:
    class SlowDripHandler(BaseHTTPRequestHandler):
        def do_POST(self):
            payload = b'{"response":"Eine langsame Antwort."}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            try:
                for byte in payload:
                    self.wfile.write(bytes([byte]))
                    self.wfile.flush()
                    time.sleep(0.03)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def log_message(self, format, *args):
            return None

    server = ThreadingHTTPServer(("127.0.0.1", 0), SlowDripHandler)
    server.daemon_threads = True
    serving = threading.Thread(target=server.serve_forever, daemon=True)
    serving.start()
    provider = LocalMistralProvider(base_url=f"http://127.0.0.1:{server.server_port}")
    provider.timeout = 0.12
    started = time.monotonic()
    try:
        with pytest.raises(ProviderError) as captured_error:
            provider.rewrite("Ein Satz.", extract_semantics("Ein Satz."), TransformOptions())
        deadline_elapsed = time.monotonic() - started
    finally:
        server.shutdown()
        server.server_close()

    assert captured_error.value.code == "provider_timeout"
    assert deadline_elapsed < 0.6


def test_mistral_reports_oversized_input_before_any_network_call(monkeypatch) -> None:
    monkeypatch.setattr(
        "urllib.request.build_opener",
        lambda *handlers: (_ for _ in ()).throw(AssertionError("network must not be touched")),
    )
    provider = LocalMistralProvider()
    text = "x" * (provider.max_characters + 1)
    with pytest.raises(ProviderError) as captured_error:
        provider.rewrite(text, extract_semantics(text), TransformOptions())
    assert captured_error.value.code == "model_input_too_long"
