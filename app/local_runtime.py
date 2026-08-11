"""Shared discovery helpers for strictly local Ollama-compatible runtimes."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from urllib.parse import urlparse

LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
LOCAL_MODEL_MAX_CHARACTERS = 12_000


def local_model_eligible(text: str, runtime_ready: bool) -> bool:
    return runtime_ready and len(text) <= LOCAL_MODEL_MAX_CHARACTERS


class InvalidLocalRuntimeUrl(ValueError):
    """Raised when a configured runtime could transmit outside loopback."""


class NoRedirect(urllib.request.HTTPRedirectHandler):
    """Refuse redirects so a loopback service cannot forward requests remotely."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        return None


def validate_loopback_base_url(value: str) -> str:
    """Return a normalized local HTTP base URL or fail closed."""
    base_url = value.rstrip("/")
    try:
        parsed = urlparse(base_url)
        port = parsed.port
    except ValueError as error:
        raise InvalidLocalRuntimeUrl("Local Mistral URL has an invalid port.") from error
    if (
        parsed.scheme != "http"
        or parsed.hostname not in LOOPBACK_HOSTS
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.params
        or parsed.query
        or parsed.fragment
        or port is None
        or port == 0
    ):
        raise InvalidLocalRuntimeUrl(
            "Local Mistral URL must be a plain loopback HTTP origin with an explicit port; "
            "remote transmission is refused."
        )
    host = "127.0.0.1" if parsed.hostname == "localhost" else parsed.hostname
    host_literal = f"[{host}]" if ":" in host else host
    return f"http://{host_literal}:{port}"


def local_mistral_ready(timeout: float = 0.8) -> bool:
    """Check the configured model without sending user text or following redirects."""
    try:
        base_url = validate_loopback_base_url(
            os.getenv("MISTRAL_BASE_URL", "http://127.0.0.1:11434")
        )
    except InvalidLocalRuntimeUrl:
        return False
    model = os.getenv("MISTRAL_MODEL", "mistral").split(":", 1)[0]
    try:
        opener = urllib.request.build_opener(NoRedirect)
        with opener.open(base_url + "/api/tags", timeout=timeout) as response:
            raw = response.read(1_000_001)
        if len(raw) > 1_000_000:
            return False
        payload = json.loads(raw)
        models = payload.get("models", []) if isinstance(payload, dict) else []
        return any(
            isinstance(item, dict) and item.get("name", "").split(":", 1)[0] == model
            for item in models
        )
    except (OSError, ValueError, KeyError, urllib.error.URLError):
        return False
