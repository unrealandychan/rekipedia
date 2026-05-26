"""Thin litellm wrapper that honours LLMConfig and env-var overrides."""
from __future__ import annotations

import logging
import os
import threading
import time
from collections.abc import Iterator
from typing import Protocol, runtime_checkable

import certifi
import litellm

# Force all httpx/ssl calls (litellm + httpx) to use certifi's CA bundle.
# This prevents SSL verification failures behind corporate proxies / WAFs.
os.environ.setdefault("SSL_CERT_FILE", certifi.where())
os.environ.setdefault("REQUESTS_CA_BUNDLE", certifi.where())

from rekipedia.models.contracts import LLMConfig

logger = logging.getLogger("rekipedia.llm")

# ── Global token counter (thread-safe) ──────────────────────────────────────

class _TokenCounter:
    """Process-wide accumulator for LLM token usage."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.calls = 0

    def add(self, usage) -> None:  # usage: litellm Usage object or None
        if usage is None:
            return
        with self._lock:
            self.prompt_tokens += getattr(usage, "prompt_tokens", 0) or 0
            self.completion_tokens += getattr(usage, "completion_tokens", 0) or 0
            self.calls += 1

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    def reset(self) -> None:
        with self._lock:
            self.prompt_tokens = 0
            self.completion_tokens = 0
            self.calls = 0

    def summary(self) -> str:
        return (
            f"Token usage — {self.calls} LLM call(s): "
            f"{self.prompt_tokens:,} prompt + {self.completion_tokens:,} completion "
            f"= {self.total_tokens:,} total"
        )


TOKEN_COUNTER = _TokenCounter()

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


@runtime_checkable
class LLMCaller(Protocol):
    """Interface for LLM callers — allows test injection via FakeCaller."""

    def call(self, system: str, prompt: str) -> str: ...
    def stream(self, system: str, prompt: str) -> Iterator[str]: ...


class FakeCaller:
    """Test double for LLMCaller. Set ``response`` to control return value."""

    def __init__(self, response: str = "fake response", chunks: list[str] | None = None) -> None:
        self.response = response
        self.chunks = chunks or [response]

    def call(self, _system: str, _prompt: str) -> str:
        return self.response

    def stream(self, _system: str, _prompt: str) -> Iterator[str]:
        yield from self.chunks


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

    def call(self, prompt: str, *, system: str = "", timeout: int | None = None, history: list[dict] | None = None) -> str:
        """Send a prompt and return the assistant text.

        *history* is a list of previous turns: [{role: user|assistant, content: str}, ...]
        *timeout* overrides the default per-call timeout (default: _DEFAULT_TIMEOUT).
        Retries up to ``_MAX_RETRIES`` times on timeout / 5xx errors.
        Raises ``litellm.exceptions.APIError`` on non-retryable upstream errors.
        """
        _original_prompt = prompt
        _MAX_TRUNCATION_ATTEMPTS = 4
        for _trunc_attempt in range(_MAX_TRUNCATION_ATTEMPTS + 1):
            messages: list[dict[str, str]] = []
            if system:
                messages.append({"role": "system", "content": system})
            if history:
                messages.extend(history)
            messages.append({"role": "user", "content": prompt})

            kwargs = {**self._base_kwargs(), "messages": messages}
            if timeout is not None:
                kwargs["timeout"] = timeout

            def _call():
                response = litellm.completion(**kwargs)
                TOKEN_COUNTER.add(getattr(response, "usage", None))
                return response.choices[0].message.content or ""

            try:
                return _with_retry(_call)
            except Exception as exc:
                _exc_str = str(exc).lower()
                _is_ctx = (
                    "contextwindow" in type(exc).__name__.lower()
                    or "contextwindowexceeded" in _exc_str
                    or ("token" in _exc_str and "limit" in _exc_str)
                    or ("context" in _exc_str and "length" in _exc_str)
                )
                if not _is_ctx or _trunc_attempt >= _MAX_TRUNCATION_ATTEMPTS:
                    raise
                # Truncate prompt by 25% per attempt
                keep_ratio = 0.75 ** (_trunc_attempt + 1)
                new_len = max(1, int(len(_original_prompt) * keep_ratio))
                prompt = _original_prompt[:new_len]
                logger.warning(
                    "Prompt too long — truncating to %d chars (attempt %d/%d)",
                    new_len, _trunc_attempt + 1, _MAX_TRUNCATION_ATTEMPTS,
                )

    def stream(self, prompt: str, *, system: str = "", history: list[dict] | None = None) -> Iterator[str]:
        """Stream response tokens as an iterator of text chunks.

        *history* is a list of previous turns: [{role: user|assistant, content: str}, ...]
        Yields each chunk's delta text as it arrives from the LLM.
        Raises ``litellm.exceptions.APIError`` on upstream errors.
        """
        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        if history:
            messages.extend(history)
        messages.append({"role": "user", "content": prompt})

        kwargs = {**self._base_kwargs(), "messages": messages, "stream": True}

        response = litellm.completion(**kwargs)
        for chunk in response:
            delta = chunk.choices[0].delta.content
            if delta:
                yield delta
