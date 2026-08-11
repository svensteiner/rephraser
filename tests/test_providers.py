import pytest

from app.providers.base import ProviderError
from app.providers.mistral_provider import LocalMistralProvider


@pytest.mark.parametrize("url", ["http://localhost.evil.com:11434", "https://localhost:11434", "http://example.org"])
def test_mistral_rejects_non_local_or_tls_urls(url: str) -> None:
    with pytest.raises(ProviderError):
        LocalMistralProvider(base_url=url)


@pytest.mark.parametrize("url", ["http://localhost:11434", "http://127.0.0.1:11434", "http://[::1]:11434"])
def test_mistral_accepts_loopback(url: str) -> None:
    assert LocalMistralProvider(base_url=url).base_url == url
