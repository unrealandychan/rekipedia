"""Thin litellm wrapper that honours LLMConfig and env-var overrides."""
from __future__ import annotations

import logging
import os
import time
from typing import Iterator

import certifi
import litellm

# Force all httpx/ssl calls (litellm + httpx) to use certifi's CA bundle.
# This prevents SSL verification failures behind corporate proxies / WAFs.
os.environ.setdefault("SSL_CERT_FILE", certifi.where())
os.environ.setdefault("REQUESTS_CA_BUNDLE", certifi.where())

from rekipedia.models.contracts import LLMConfig

logger = logging.getLogger("rekipedia.llm")

# Timeout per LLM call in seconds — wiki pages can be long, allow generous time
_DEFAULT_TIMEOUT = int(os.environ.get("REKIPEDIA_TIMEOUT", "180"))
# Max retry attempts on timeout / 5xx errors
_MAX_RETRIES = int(os.environ.get("REKIPEDIA_MAX_RETRIES", "3"))
# Retryable litellm exception types
_RETRYABLE = (
    litellm.Timeout,
    litellm.ServiceUnavailableError,
    litellm.InternalServerError,
    litellm.RateLimitError,
)


def _with_retry(fn, max_retries: int = _MAX_RETRIES):
    """Call *fn()* with exponential backoff on retryable errors."""
    delay = 5.0
    for attempt in range(1, max_retries + 1):
        try:
            return fn()
        except _RETRYABLE as exc:
            if attempt == max_retries:
                raise
            wait = delay * (2 ** (attempt - 1))  # 5s, 10s, 20s
            logger.warning(
                "LLM call failed (%s: %s) — retrying in %.0fs (attempt %d/%d)",
                type(exc).__name__, exc, wait, attempt, max_retries,
            )
            time.sleep(wait)


class LLMClient:
    """Stateless LLM caller.  Thread-safe (litellm is stateless per call)."""

    def __init__(self, config: LLMConfig) -> None:
        # Env-var overrides take precedence over config file values
        self._model = os.environ.get("REKIPEDIA_MODEL") or config.model
        self._api_key = os.environ.get("REKIPEDIA_API_KEY") or config.api_key or None
        self._base_url = os.environ.get("REKIPEDIA_BASE_URL") or config.base_url or None
        self._temperature = config.temperature

    def _base_kwargs(self) -> dict:
        kwargs: dict = {
            "model": self._model,
            "temperature": self._temperature,
            "timeout": _DEFAULT_TIMEOUT,
        }
        if self._api_key:
            kwargs["api_key"] = self._api_key
        if self._base_url:
            kwargs["base_url"] = self._base_url
        return kwargs

    def call(self, prompt: str, *, system: str = "", timeout: int | None = None) -> str:
        """Send a prompt and return the assistant text.

        *timeout* overrides the default per-call timeout (default: _DEFAULT_TIMEOUT).
        Retries up to ``_MAX_RETRIES`` times on timeout / 5xx errors.
        Raises ``litellm.exceptions.APIError`` on non-retryable upstream errors.
        """
        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        kwargs = {**self._base_kwargs(), "messages": messages}
        if timeout is not None:
            kwargs["timeout"] = timeout

        def _call():
            response = litellm.completion(**kwargs)
            return response.choices[0].message.content or ""

        return _with_retry(_call)

    def stream(self, prompt: str, *, system: str = "") -> Iterator[str]:
        """Stream response tokens as an iterator of text chunks.

        Yields each chunk's delta text as it arrives from the LLM.
        Raises ``litellm.exceptions.APIError`` on upstream errors.
        """
        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        kwargs = {**self._base_kwargs(), "messages": messages, "stream": True}
        if self._api_key:
            kwargs["api_key"] = self._api_key
        if self._base_url:
            kwargs["base_url"] = self._base_url

        response = litellm.completion(**kwargs)
        for chunk in response:
            delta = chunk.choices[0].delta.content
            if delta:
                yield delta
