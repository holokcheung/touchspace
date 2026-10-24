"""Optional Gemini help for understanding free-form questions.

Gemini never answers. It only maps a question the rule parser couldn't handle onto
one of our intents and onto place ids that already exist on the map. The JSON schema
limits it to those ids, so it can't introduce a place. The answer is then produced
by the normal grounded pipeline from map data.

REST: POST https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent
      header x-goog-api-key, JSON output via generationConfig.responseMimeType/responseSchema.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass

import httpx

API_BASE = "https://generativelanguage.googleapis.com/v1beta"
DEFAULT_MODEL = "gemini-3.8-flash"
INTENTS = ["overview", "list", "where", "nearby", "route", "whereami", "help", "unknown"]
NONE = "none"


@dataclass(frozen=True)
class GeminiConfig:
    api_key: str | None
    model: str
    timeout_s: float = 8.0

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    @classmethod
    def from_env(cls) -> "GeminiConfig":
        return cls(api_key=os.environ.get("GEMINI_API_KEY") or None, model=os.environ.get("GEMINI_MODEL") or DEFAULT_MODEL)


@dataclass(frozen=True)
class Interpretation:
    intent: str
    target_id: str | None
    origin_id: str | None


class GeminiInterpreter:
    def __init__(self, config: GeminiConfig, transport: httpx.BaseTransport | None = None):
        self.config = config
        self._client = httpx.Client(timeout=config.timeout_s, transport=transport)

    @property
    def enabled(self) -> bool:
        return self.config.enabled

    def interpret(self, question: str, places: list[tuple[str, str, str]], last_place_id: str | None) -> Interpretation | None:
        """places: (id, name, kind). Returns None when disabled, failing, or unsure."""
        if not self.enabled or not places:
            return None
        ids = [p[0] for p in places]
        listing = "\n".join(f"- {pid}: {name} ({kind})" for pid, name, kind in places)
        prompt = (
            "You convert a question about an indoor floor plan into a structured request for a navigation app "
            "used by blind and low-vision people. Do not answer the question.\n"
            f"Places on this map (id: name (kind)):\n{listing}\n"
            f"The previous answer was about: {last_place_id or 'nothing yet'}.\n"
            "Intents: overview = describe the whole space; list = which places exist; where = location of one place; "
            "nearby = what is near a place; route = directions to a place (origin optional); whereami = the user's "
            "position; help = how to use the app; unknown = not about this map.\n"
            "Pick place ids only from the list, or 'none'. If unsure, use intent 'unknown'.\n"
            f"Question: {question}"
        )
        schema = {
            "type": "OBJECT",
            "properties": {
                "intent": {"type": "STRING", "enum": INTENTS},
                "target_id": {"type": "STRING", "enum": [*ids, NONE]},
                "origin_id": {"type": "STRING", "enum": [*ids, NONE]},
            },
            "required": ["intent", "target_id", "origin_id"],
        }
        body = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0, "responseMimeType": "application/json", "responseSchema": schema},
        }
        try:
            res = self._client.post(
                f"{API_BASE}/models/{self.config.model}:generateContent",
                headers={"x-goog-api-key": self.config.api_key or ""},
                json=body,
            )
            res.raise_for_status()
            text = res.json()["candidates"][0]["content"]["parts"][0]["text"]
            data = json.loads(text)
        except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError):
            return None
        intent = data.get("intent")
        if intent not in INTENTS or intent == "unknown":
            return None

        def valid(v: object) -> str | None:
            return v if isinstance(v, str) and v in ids else None

        target, origin = valid(data.get("target_id")), valid(data.get("origin_id"))
        if intent in ("where", "nearby", "route") and target is None:
            return None
        return Interpretation(intent=intent, target_id=target, origin_id=origin)
