"""Cartesia speech for TouchSpace: text-to-speech (Sonic) and speech-to-text (Ink).

The API key never leaves the server. The browser calls our `/api/tts` and
`/api/stt` endpoints. When Cartesia is not configured or not reachable, those
endpoints return a clear "unavailable" error, and the frontend falls back to the
browser's built-in speech synthesis and recognition, so voice keeps working
without paid services.

API reference (Cartesia-Version 2026-08-14):
  POST https://api.cartesia.ai/tts/bytes  JSON {model_id, transcript, voice:{id}, output_format, language}
  POST https://api.cartesia.ai/stt        multipart {file, model="ink-whisper", language}
  GET  https://api.cartesia.ai/voices     list voices (used only to pick a default voice)
"""

from __future__ import annotations

import hashlib
import os
import threading
from collections import OrderedDict
from dataclasses import dataclass

import httpx

API_BASE = "https://api.cartesia.ai"
API_VERSION = "2026-08-14"
DEFAULT_TTS_MODEL = "sonic-3.6"
STT_MODEL = "ink-whisper"
MAX_TTS_CHARS = 2000
MAX_STT_BYTES = 10 * 1024 * 1024
CACHE_ITEMS = 64


class VoiceUnavailable(RuntimeError):
    """Cartesia is not configured, or the request failed. The message is safe to show."""


@dataclass(frozen=True)
class VoiceConfig:
    api_key: str | None
    voice_id: str | None
    tts_model: str
    timeout_s: float = 20.0

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    @classmethod
    def from_env(cls) -> "VoiceConfig":
        return cls(
            api_key=os.environ.get("CARTESIA_API_KEY") or None,
            voice_id=os.environ.get("CARTESIA_VOICE_ID") or None,
            tts_model=os.environ.get("CARTESIA_TTS_MODEL") or DEFAULT_TTS_MODEL,
        )


class CartesiaVoice:
    def __init__(self, config: VoiceConfig, transport: httpx.BaseTransport | None = None):
        self.config = config
        self._client = httpx.Client(base_url=API_BASE, timeout=config.timeout_s, transport=transport)
        self._voice_id = config.voice_id
        self._cache: OrderedDict[str, bytes] = OrderedDict()
        self._lock = threading.Lock()

    def _headers(self) -> dict[str, str]:
        if not self.config.api_key:
            raise VoiceUnavailable("Cartesia voice is not configured on this server.")
        return {"Authorization": f"Bearer {self.config.api_key}", "Cartesia-Version": API_VERSION}

    def _request(self, method: str, path: str, **kwargs) -> httpx.Response:
        try:
            res = self._client.request(method, path, headers=self._headers(), **kwargs)
        except httpx.HTTPError as exc:
            raise VoiceUnavailable(f"Could not reach Cartesia ({type(exc).__name__}).") from exc
        if res.status_code in (401, 403):
            raise VoiceUnavailable("Cartesia rejected the API key. Check CARTESIA_API_KEY on the server.")
        if res.status_code == 429:
            raise VoiceUnavailable("Cartesia rate limit reached. Try again in a moment.")
        if res.status_code >= 400:
            detail = res.text[:200].strip()
            raise VoiceUnavailable(f"Cartesia returned an error ({res.status_code}){': ' + detail if detail else ''}.")
        return res

    def voice_id(self) -> str:
        """Configured voice, or the first English voice available to this account."""
        if self._voice_id:
            return self._voice_id
        res = self._request("GET", "/voices", params={"limit": 100})
        body = res.json()
        voices = body.get("data", []) if isinstance(body, dict) else body
        english = [v for v in voices if isinstance(v, dict) and str(v.get("language", "")).startswith("en") and v.get("id")]
        if not english:
            raise VoiceUnavailable("No English Cartesia voice found. Set CARTESIA_VOICE_ID on the server.")
        self._voice_id = english[0]["id"]
        return self._voice_id

    def synthesize(self, text: str, *, speed: float = 1.0) -> bytes:
        """MP3 audio for `text`. Identical requests are served from a small in-memory cache."""
        text = " ".join(text.split())
        if not text:
            raise ValueError("Nothing to say.")
        if len(text) > MAX_TTS_CHARS:
            raise ValueError(f"Text is too long to speak at once (limit {MAX_TTS_CHARS} characters).")
        speed = min(1.5, max(0.6, speed))
        voice = self.voice_id()
        key = hashlib.sha256(f"{self.config.tts_model}|{voice}|{speed}|{text}".encode()).hexdigest()
        with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)
                return self._cache[key]
        payload = {
            "model_id": self.config.tts_model,
            "transcript": text,
            "voice": {"id": voice},
            "output_format": {"container": "mp3", "sample_rate": 44100, "bit_rate": 128000},
            "language": "en",
        }
        if speed != 1.0:
            payload["generation_config"] = {"speed": speed}
        audio = self._request("POST", "/tts/bytes", json=payload).content
        if not audio:
            raise VoiceUnavailable("Cartesia returned empty audio.")
        with self._lock:
            self._cache[key] = audio
            while len(self._cache) > CACHE_ITEMS:
                self._cache.popitem(last=False)
        return audio

    def transcribe(self, audio: bytes, filename: str, content_type: str | None) -> str:
        """Text from a short recording (webm/ogg/mp4/wav/mp3...)."""
        if not audio:
            raise ValueError("The recording is empty.")
        if len(audio) > MAX_STT_BYTES:
            raise ValueError("The recording is too long.")
        res = self._request(
            "POST", "/stt",
            files={"file": (filename or "speech.webm", audio, content_type or "application/octet-stream")},
            data={"model": STT_MODEL, "language": "en"},
        )
        text = res.json().get("text")
        if not isinstance(text, str):
            raise VoiceUnavailable("Cartesia returned no transcript.")
        return text.strip()
