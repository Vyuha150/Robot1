"""
bonbon_tts.core.text_processor
================================
TextProcessor — validates, sanitises, and chunks TTS input text.

Responsibilities
----------------
1. **Validation** — reject empty strings, non-string types, and text
   that exceeds the hard maximum (prevents run-away LLM outputs).
2. **Sanitisation** — strip control characters, normalise Unicode,
   collapse repeated whitespace.
3. **Truncation** — soft-limit long text at a word boundary and append
   an ellipsis so the robot doesn't silently drop sentences.
4. **Chunking** — split long text into clause-sized pieces for low-latency
   incremental playback.  Splits prefer sentence endings, then commas,
   then hard byte boundaries.

All operations are pure (no I/O, no threading) and raise
:class:`TextValidationError` on hard failures.
"""
from __future__ import annotations

import re
import unicodedata
from typing import List, Tuple


# ── Exception ──────────────────────────────────────────────────────────────────

class TextValidationError(Exception):
    """Raised when input text cannot be processed."""

    def __init__(self, message: str, code: str = "TEXT_INVALID") -> None:
        super().__init__(message)
        self.code = code


# ── Processor ─────────────────────────────────────────────────────────────────

class TextProcessor:
    """
    Stateless text processing pipeline for TTS input.

    Parameters
    ----------
    max_chars:
        Soft limit: text is truncated at a word boundary.
        Default 2000 characters.
    chunk_size:
        Target size for chunked utterances.
        Default 500 characters.

    Example
    -------
    ::

        tp = TextProcessor()
        chunks, truncated = tp.process("Hello!  How can I help you today?")
        # → (["Hello! How can I help you today?"], False)

        chunks, truncated = tp.process(very_long_text)
        # → (["Sentence one.", "Sentence two..."], True if truncated)
    """

    # Absolute hard ceiling — reject rather than truncate
    _HARD_MAX = 10_000

    def __init__(
        self,
        max_chars:  int = 2_000,
        chunk_size: int = 500,
    ) -> None:
        if max_chars < 10:
            raise ValueError("max_chars must be >= 10")
        if chunk_size < 10:
            raise ValueError("chunk_size must be >= 10")
        self._max_chars  = max_chars
        self._chunk_size = chunk_size

    # ── Public interface ───────────────────────────────────────────────────────

    def validate(self, text: object) -> Tuple[bool, str]:
        """
        Validate *text* without processing it.

        Returns
        -------
        tuple[bool, str]
            ``(True, "")`` when valid; ``(False, reason)`` when not.
        """
        if not isinstance(text, str):
            return False, f"text must be str, got {type(text).__name__}"
        if not text.strip():
            return False, "text is empty or whitespace-only"
        if len(text) > self._HARD_MAX:
            return False, f"text length {len(text)} exceeds hard maximum {self._HARD_MAX}"
        return True, ""

    def sanitize(self, text: str) -> str:
        """
        Clean *text* for safe TTS input.

        Steps
        -----
        1. Remove C0/C1 control characters (except ``\\n`` and ``\\t``).
        2. NFC-normalise Unicode.
        3. Collapse runs of whitespace/tabs to a single space.
        4. Collapse multiple blank lines to a single space.
        5. Strip leading/trailing whitespace.
        """
        # Remove control chars except newline (0x0a) and tab (0x09)
        text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)
        # NFC normalise (e.g. combining diacritics → precomposed)
        text = unicodedata.normalize("NFC", text)
        # Collapse horizontal whitespace
        text = re.sub(r"[ \t]+", " ", text)
        # Replace newlines with a space
        text = re.sub(r"\n+", " ", text)
        return text.strip()

    def truncate_if_needed(self, text: str) -> Tuple[str, bool]:
        """
        Truncate *text* at a word boundary if it exceeds ``max_chars``.

        Returns
        -------
        tuple[str, bool]
            ``(text, was_truncated)``.
        """
        if len(text) <= self._max_chars:
            return text, False

        # Truncate at word boundary
        cut   = text[: self._max_chars]
        space = cut.rfind(" ")
        if space > self._max_chars * 0.7:
            cut = cut[:space]

        return cut.rstrip() + "…", True

    def chunk(self, text: str, chunk_size: Optional[int] = None) -> List[str]:  # noqa: F821
        """
        Split *text* into clause-sized pieces for incremental playback.

        Splitting strategy (in order of preference):
        1. Sentence endings (``.``, ``!``, ``?`` followed by space).
        2. Clause boundaries (``,``, ``;``, ``:`` followed by space).
        3. Hard split at *chunk_size* bytes.

        Parameters
        ----------
        chunk_size:
            Override the instance-level chunk size for this call.
        """
        size = chunk_size if chunk_size is not None else self._chunk_size
        if len(text) <= size:
            return [text] if text else []

        # Prefer splitting at sentence boundaries
        sentences = re.split(r"(?<=[.!?])\s+", text)
        return self._pack_items(sentences, size)

    def process(self, text: object) -> Tuple[List[str], bool]:
        """
        Full pipeline: validate → sanitise → truncate → chunk.

        Parameters
        ----------
        text:
            Raw input (any type; non-str raises :class:`TextValidationError`).

        Returns
        -------
        tuple[list[str], bool]
            ``(chunks, was_truncated)`` where *chunks* is a non-empty list
            of ready-to-synthesise strings.

        Raises
        ------
        TextValidationError
            If the text fails validation.
        """
        ok, reason = self.validate(text)
        if not ok:
            raise TextValidationError(reason)

        cleaned    = self.sanitize(str(text))
        if not cleaned:
            raise TextValidationError("text is empty after sanitisation")

        truncated, was_truncated = self.truncate_if_needed(cleaned)
        chunks     = self.chunk(truncated)

        return chunks, was_truncated

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _pack_items(self, items: List[str], size: int) -> List[str]:
        """
        Greedily pack *items* into chunks of at most *size* chars,
        splitting oversized items at commas or hard boundaries.
        """
        chunks: List[str] = []
        current           = ""

        for item in items:
            if not item:
                continue
            if len(item) > size:
                # Too long on its own — split further
                if current:
                    chunks.append(current.strip())
                    current = ""
                chunks.extend(self._split_at_commas(item, size))
            elif len(current) + len(item) + 1 <= size:
                current = (current + " " + item).strip()
            else:
                if current:
                    chunks.append(current.strip())
                current = item

        if current:
            chunks.append(current.strip())

        return [c for c in chunks if c]

    def _split_at_commas(self, text: str, size: int) -> List[str]:
        """Split *text* at commas, then hard-truncate if still too long."""
        parts = re.split(r"(?<=,)\s+", text)
        packed = self._pack_items(parts, size)
        if not packed:
            return []
        # Hard-split anything still over size
        result: List[str] = []
        for chunk in packed:
            if len(chunk) <= size:
                result.append(chunk)
            else:
                result.extend(chunk[i : i + size] for i in range(0, len(chunk), size))
        return result


# Fix missing import for Optional (Python < 3.10 compat)
from typing import Optional  # noqa: E402
