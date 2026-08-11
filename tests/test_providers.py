import json

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
            assert timeout == 45
            captured.update(json.loads(request.data))
            return Response()

    monkeypatch.setattr("urllib.request.build_opener", lambda *handlers: Opener())
    text = "Ein klarer Satz."
    result = LocalMistralProvider().rewrite(text, extract_semantics(text), TransformOptions())
    assert result == text
    assert captured["options"] == {"temperature": 0, "seed": 42, "num_predict": 96}
    assert captured["stream"] is False
