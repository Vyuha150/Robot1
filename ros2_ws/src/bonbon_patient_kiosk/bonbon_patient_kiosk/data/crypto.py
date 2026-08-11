"""AES-256-GCM field-level encryption for PHI at rest.

Falls back to a clearly-labelled no-op codec if pycryptodome isn't
installed, so the rest of the package still imports for unit tests that
don't care about encryption — but that fallback is loud (logged once) and
must never be relied on outside test mode.
"""

from __future__ import annotations

import base64
import json
import logging
import os

logger = logging.getLogger(__name__)

try:
    from Crypto.Cipher import AES
    from Crypto.Random import get_random_bytes

    _CRYPTO_AVAILABLE = True
except ImportError:
    _CRYPTO_AVAILABLE = False
    logger.warning(
        "pycryptodome not available — PHI encryption at rest is DISABLED. "
        "Install pycryptodome before any real deployment."
    )


class PHICipher:
    """Encrypt/decrypt JSON-serialisable payloads with AES-256-GCM."""

    def __init__(self, key_hex: str) -> None:
        self._key = bytes.fromhex(key_hex)
        if _CRYPTO_AVAILABLE and len(self._key) != 32:
            raise ValueError("encryption key must be 32 bytes (64 hex chars)")

    def encrypt(self, payload: dict) -> str:
        plaintext = json.dumps(payload).encode("utf-8")
        if not _CRYPTO_AVAILABLE:
            return "plaintext:" + base64.b64encode(plaintext).decode("ascii")
        nonce = get_random_bytes(12)
        cipher = AES.new(self._key, AES.MODE_GCM, nonce=nonce)
        ciphertext, tag = cipher.encrypt_and_digest(plaintext)
        blob = nonce + tag + ciphertext
        return "aesgcm:" + base64.b64encode(blob).decode("ascii")

    def decrypt(self, token: str) -> dict:
        scheme, _, encoded = token.partition(":")
        raw = base64.b64decode(encoded)
        if scheme == "plaintext":
            return json.loads(raw.decode("utf-8"))
        if scheme != "aesgcm":
            raise ValueError(f"unknown encryption scheme: {scheme}")
        if not _CRYPTO_AVAILABLE:
            raise RuntimeError("cannot decrypt aesgcm payload without pycryptodome")
        nonce, tag, ciphertext = raw[:12], raw[12:28], raw[28:]
        cipher = AES.new(self._key, AES.MODE_GCM, nonce=nonce)
        plaintext = cipher.decrypt_and_verify(ciphertext, tag)
        return json.loads(plaintext.decode("utf-8"))


def new_key_hex() -> str:
    """Generate a fresh 32-byte key as a hex string (for setup tooling)."""
    return os.urandom(32).hex()
