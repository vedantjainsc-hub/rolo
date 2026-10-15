"""Model client abstraction.

This is the ONLY module that knows about Ollama. Everything else talks to a
`ModelClient`, so an on-device client (phone / LiteRT / MediaPipe) can replace
`OllamaClient` later without touching the rest of the backend.
"""
from __future__ import annotations

import logging
from typing import Any, Protocol, runtime_checkable

import httpx

from app import config

log = logging.getLogger("rolo.model")


# ---- Errors (backend-agnostic; service.py maps these to friendly messages) ----

class ModelError(Exception):
    """Base class for model failures."""


class ModelUnavailable(ModelError):
    """The model runtime could not be reached."""


class ModelNotInstalled(ModelError):
    """The runtime is up but the configured model is not installed."""


class ModelTimeout(ModelError):
    """The model did not answer in time."""


class ModelBadResponse(ModelError):
    """The runtime answered with something unusable (HTTP error, empty body...)."""


@runtime_checkable
class ModelClient(Protocol):
    name: str

    def chat_json(self, messages: list[dict[str, str]], schema: dict[str, Any]) -> str:
        """Send chat messages, constrained to `schema`; return the raw text reply."""
        ...

    def status(self) -> tuple[bool, str | None]:
        """Return (available, detail). detail explains why when unavailable."""
        ...


class OllamaClient:
    """Talks to a local Ollama server over HTTP."""

    def __init__(
        self,
        model: str | None = None,
        base_url: str | None = None,
        timeout_s: float | None = None,
    ) -> None:
        self.name = model or config.MODEL_NAME
        self.base_url = (base_url or config.OLLAMA_URL).rstrip("/")
        self.timeout_s = timeout_s or config.MODEL_TIMEOUT_S

    def chat_json(self, messages: list[dict[str, str]], schema: dict[str, Any]) -> str:
        body = {
            "model": self.name,
            "messages": messages,
            "stream": False,
            "think": False,  # qwen3 and other thinking models: no reasoning trace
            "format": schema,
            "options": {"temperature": 0.2, "num_ctx": 8192, "num_predict": 1200},
        }
        try:
            with httpx.Client(timeout=httpx.Timeout(self.timeout_s, connect=5.0)) as client:
                resp = client.post(f"{self.base_url}/api/chat", json=body)
        except (httpx.ConnectTimeout, httpx.PoolTimeout) as exc:
            # Never got a connection: the runtime is unreachable, not slow.
            raise ModelUnavailable(str(exc)) from exc
        except httpx.TimeoutException as exc:
            raise ModelTimeout(str(exc)) from exc
        except httpx.TransportError as exc:  # connection refused, DNS, etc.
            raise ModelUnavailable(str(exc)) from exc

        if resp.status_code == 404:
            raise ModelNotInstalled(_error_text(resp))
        if resp.status_code >= 400:
            text = _error_text(resp)
            if "not found" in text.lower() and "model" in text.lower():
                raise ModelNotInstalled(text)
            raise ModelBadResponse(f"HTTP {resp.status_code}: {text[:200]}")

        try:
            data = resp.json()
        except ValueError as exc:
            raise ModelBadResponse("Non-JSON HTTP body from Ollama") from exc
        content = (data.get("message") or {}).get("content")
        if not isinstance(content, str) or not content.strip():
            raise ModelBadResponse("Empty reply from model")
        return content

    def status(self) -> tuple[bool, str | None]:
        try:
            with httpx.Client(timeout=3.0) as client:
                resp = client.get(f"{self.base_url}/api/tags")
            resp.raise_for_status()
            models = resp.json().get("models", [])
        except (httpx.HTTPError, ValueError):
            return False, f"Ollama isn't reachable at {self.base_url}. Start Ollama."
        names: set[str] = set()
        for m in models:
            for key in ("name", "model"):
                n = m.get(key)
                if n:
                    names.add(n)
                    if n.endswith(":latest"):
                        names.add(n[: -len(":latest")])
        if self.name in names or f"{self.name}:latest" in names:
            return True, None
        return False, f"Model {self.name} isn't installed. Run: ollama pull {self.name}"


def _error_text(resp: httpx.Response) -> str:
    try:
        return str(resp.json().get("error", resp.text))
    except ValueError:
        return resp.text


_client: ModelClient | None = None


def get_model_client() -> ModelClient:
    """Process-wide client. Swap this factory to change model backends."""
    global _client
    if _client is None:
        _client = OllamaClient()
    return _client


def set_model_client(client: ModelClient | None) -> None:
    """Override the client (used by tests)."""
    global _client
    _client = client
