"""sarvam_api_client — thin HTTP client for Sarvam's cloud API, used ONLY
when sarvam_capability_detector confirms mode="api" (API key present AND
cloud explicitly enabled). This module makes no network call at import
time and never constructs a request unless the caller has already gone
through SarvamCapabilities.

Endpoint paths below follow Sarvam's publicly documented REST API shape
as of this package's authoring, but were NOT verified against a live
call in this session (no API key/network access available) -- treat the
exact paths as "best-known, needs a live smoke-test before first real
use," not a channel this session has confirmed working. This is the
honest distinction rule 1 requires: the CODE is real and ready, the
CONNECTIVITY is unverified.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass

_DEFAULT_BASE_URL = "https://api.sarvam.ai"


class SarvamAPIError(Exception):
    pass


@dataclass
class SarvamAPIClient:
    api_key: str
    base_url: str = _DEFAULT_BASE_URL
    timeout_sec: float = 15.0

    @classmethod
    def from_env(cls) -> "SarvamAPIClient":
        key = os.environ.get("SARVAM_API_KEY", "")
        if not key:
            raise SarvamAPIError("SARVAM_API_KEY is not set -- caller must check sarvam_capability_detector first")
        base_url = os.environ.get("SARVAM_API_BASE_URL", _DEFAULT_BASE_URL)
        return cls(api_key=key, base_url=base_url)

    def _post(self, path: str, payload: dict) -> dict:
        url = f"{self.base_url.rstrip('/')}{path}"
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url, data=data, method="POST",
            headers={"Content-Type": "application/json", "api-subscription-key": self.api_key},
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_sec) as resp:  # noqa: S310 -- URL is env-configured, never user input
                return json.loads(resp.read())
        except urllib.error.URLError as exc:
            raise SarvamAPIError(f"Sarvam API request to {path} failed: {exc}") from exc

    def speech_to_text(self, audio_bytes: bytes, language_code: str = "unknown") -> str:
        """Best-known shape for Sarvam's speech-to-text endpoint -- verify
        against current Sarvam API docs before first real use (see module
        docstring)."""
        raise NotImplementedError(
            "Sarvam STT requires multipart audio upload, not a JSON POST -- implement the exact "
            "multipart contract once real API access is available to verify the request/response shape against"
        )

    def text_to_speech(self, text: str, language_code: str, speaker: str = "meera") -> bytes:
        result = self._post("/text-to-speech", {"inputs": [text], "target_language_code": language_code, "speaker": speaker})
        audio_b64 = result.get("audios", [None])[0]
        if not audio_b64:
            raise SarvamAPIError("Sarvam TTS response did not include audio data")
        import base64

        return base64.b64decode(audio_b64)

    def translate(self, text: str, source_language_code: str, target_language_code: str) -> str:
        result = self._post(
            "/translate",
            {"input": text, "source_language_code": source_language_code, "target_language_code": target_language_code},
        )
        translated = result.get("translated_text")
        if not translated:
            raise SarvamAPIError("Sarvam translate response did not include translated_text")
        return translated
