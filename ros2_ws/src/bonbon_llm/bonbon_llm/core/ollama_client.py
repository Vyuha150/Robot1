"""
bonbon_llm.core.ollama_client
==============================
Thread-safe wrapper around the Ollama HTTP API.

Tries the official ``ollama`` Python SDK first; falls back to plain
``urllib.request`` so the node starts even when the SDK is not installed
(degraded mode — only /generate endpoint is used as fallback).

Usage
-----
    client = OllamaClient(cfg.ollama)
    if client.is_available():
        result = client.chat([{"role": "user", "content": "Hello"}])
        print(result.text)
"""

from __future__ import annotations

import json
import logging
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass

from bonbon_llm.config.llm_config import OllamaConfig

logger = logging.getLogger(__name__)


# ── Response type ─────────────────────────────────────────────────────────────


@dataclass
class OllamaResponse:
    text: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    latency_ms: float
    done: bool = True
    error: str | None = None

    @property
    def is_error(self) -> bool:
        return self.error is not None


# ── Client ────────────────────────────────────────────────────────────────────


class OllamaClient:
    """
    Thread-safe Ollama API client.

    Prefers the ``ollama`` SDK for streaming-safe handling; falls back
    to ``urllib`` POST to /api/generate when the SDK is absent.
    """

    def __init__(self, cfg: OllamaConfig) -> None:
        self._cfg = cfg
        self._lock = threading.Lock()
        self._sdk = None  # lazily loaded
        self._sdk_checked = False

    # ── Availability ──────────────────────────────────────────────────────────

    def is_available(self) -> bool:
        """Return True if Ollama server responds within 2 seconds."""
        try:
            url = f"{self._cfg.base_url}/api/tags"
            req = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(req, timeout=2.0):
                return True
        except Exception:
            return False

    # ── Chat interface ────────────────────────────────────────────────────────

    def chat(
        self,
        messages: list[dict[str, str]],
        temperature: float | None = None,
        max_tokens: int | None = None,
        system: str | None = None,
    ) -> OllamaResponse:
        """
        Send a chat completion request.

        Parameters
        ----------
        messages:    List of {"role": "user"|"assistant"|"system", "content": "..."}
        temperature: Override cfg.temperature
        max_tokens:  Override cfg.max_tokens
        system:      Prepend a system message (convenience shortcut)
        """
        if system:
            messages = [{"role": "system", "content": system}] + list(messages)

        t_start = time.perf_counter()
        try:
            sdk = self._get_sdk()
            if sdk:
                return self._chat_sdk(sdk, messages, temperature, max_tokens, t_start)
            else:
                return self._chat_http(messages, temperature, max_tokens, t_start)
        except Exception as exc:
            latency = (time.perf_counter() - t_start) * 1000.0
            logger.error("Ollama chat error: %s", exc)
            return OllamaResponse(
                text="",
                model=self._cfg.model,
                prompt_tokens=0,
                completion_tokens=0,
                latency_ms=latency,
                done=False,
                error=str(exc),
            )

    def generate(
        self,
        prompt: str,
        system: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> OllamaResponse:
        """Single-turn generate (wraps chat with a user message)."""
        messages = [{"role": "user", "content": prompt}]
        return self.chat(messages, temperature=temperature, max_tokens=max_tokens, system=system)

    # ── SDK path ──────────────────────────────────────────────────────────────

    def _get_sdk(self):
        if not self._sdk_checked:
            self._sdk_checked = True
            try:
                import ollama as _sdk

                self._sdk = _sdk
            except ImportError:
                logger.info("ollama SDK not installed; using urllib fallback")
                self._sdk = None
        return self._sdk

    def _chat_sdk(self, sdk, messages, temperature, max_tokens, t_start):
        temp = temperature if temperature is not None else self._cfg.temperature
        toks = max_tokens if max_tokens is not None else self._cfg.max_tokens

        with self._lock:
            resp = sdk.chat(
                model=self._cfg.model,
                messages=messages,
                options={
                    "temperature": temp,
                    "num_predict": toks,
                    "num_ctx": self._cfg.num_ctx,
                },
            )

        latency = (time.perf_counter() - t_start) * 1000.0
        msg = resp.get("message", {}) if isinstance(resp, dict) else resp.message
        content = (msg.get("content", "") if isinstance(msg, dict) else msg.content) or ""

        usage = resp.get("usage", {}) if isinstance(resp, dict) else {}
        return OllamaResponse(
            text=content.strip(),
            model=self._cfg.model,
            prompt_tokens=usage.get("prompt_tokens", 0),
            completion_tokens=usage.get("completion_tokens", len(content.split())),
            latency_ms=latency,
        )

    # ── HTTP fallback path ────────────────────────────────────────────────────

    def _chat_http(self, messages, temperature, max_tokens, t_start):
        """POST to /api/chat using stdlib urllib (no SDK dependency)."""
        temp = temperature if temperature is not None else self._cfg.temperature
        toks = max_tokens if max_tokens is not None else self._cfg.max_tokens

        payload = json.dumps(
            {
                "model": self._cfg.model,
                "messages": messages,
                "stream": False,
                "options": {
                    "temperature": temp,
                    "num_predict": toks,
                    "num_ctx": self._cfg.num_ctx,
                },
            }
        ).encode()

        url = f"{self._cfg.base_url}/api/chat"
        req = urllib.request.Request(
            url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        with self._lock, urllib.request.urlopen(req, timeout=self._cfg.timeout_sec) as resp:
            body = json.loads(resp.read().decode())

        latency = (time.perf_counter() - t_start) * 1000.0
        content = body.get("message", {}).get("content", "") or ""
        return OllamaResponse(
            text=content.strip(),
            model=self._cfg.model,
            prompt_tokens=0,
            completion_tokens=len(content.split()),
            latency_ms=latency,
        )
