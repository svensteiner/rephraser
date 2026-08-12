"""Shared discovery helpers for strictly local Ollama-compatible runtimes."""

from __future__ import annotations

import json
import os
import queue
import threading
import urllib.error
import urllib.request
from urllib.parse import urlparse

LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
LOCAL_MODEL_MAX_CHARACTERS = 12_000
MISTRAL_PREFLIGHT_TIMEOUT_SECONDS = 0.5


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


def _read_runtime_tags_with_deadline(base_url: str, timeout: float) -> bytes | None:
    """Read local model tags within a hard wall-clock deadline.

    ``urllib`` applies its timeout to idle socket operations.  A damaged or stalled
    local runtime could still drip bytes indefinitely, which is unacceptable for a
    startup or preflight check in the desktop UI.  This helper never sends document
    content and returns ``None`` on every failure or deadline expiry.
    """
    deadline = max(0.05, float(timeout))
    completed: queue.Queue[tuple[str, object]] = queue.Queue(maxsize=1)
    active_response: dict[str, object] = {}
    cancelled = threading.Event()

    def request_worker() -> None:
        try:
            opener = urllib.request.build_opener(NoRedirect)
            with opener.open(base_url + "/api/tags", timeout=deadline) as response:
                active_response["value"] = response
                # The main thread can reach its deadline while ``open`` is still
                # establishing a connection.  Do not start a body read if the
                # response arrives after that deadline; leaving the context closes it.
                if cancelled.is_set():
                    return
                raw = response.read(1_000_001)
            if cancelled.is_set():
                return
            completed.put(("result", raw))
        except Exception as error:
            if not cancelled.is_set():
                completed.put(("error", error))

    worker = threading.Thread(target=request_worker, daemon=True, name="local-mistral-preflight")
    worker.start()
    worker.join(deadline)
    if worker.is_alive():
        # Set cancellation before reading ``active_response``. If ``open`` returns
        # immediately after this lookup, the worker sees the event and closes its
        # own response instead of blocking in ``read`` indefinitely.
        cancelled.set()
        response = active_response.get("value")
        if response is not None:
            def close_response() -> None:
                try:
                    response.close()  # type: ignore[union-attr]
                except Exception:
                    pass

            # Closing an HTTP response can itself wait for a concurrent read.  Keep
            # cleanup out of the UI-critical deadline just as the generation adapter
            # does for a slow model response.
            threading.Thread(
                target=close_response,
                daemon=True,
                name="local-mistral-preflight-cleanup",
            ).start()
        return None
    try:
        status, value = completed.get_nowait()
    except queue.Empty:
        return None
    return value if status == "result" and isinstance(value, bytes) else None


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
        raw = _read_runtime_tags_with_deadline(base_url, timeout)
        if raw is None:
            return False
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


def preflight_local_mistral() -> bool:
    """Quick, local-only readiness check immediately before a thorough rewrite."""
    return local_mistral_ready(timeout=MISTRAL_PREFLIGHT_TIMEOUT_SECONDS)
