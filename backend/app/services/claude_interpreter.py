"""Optional Claude help for understanding free-form questions.

Claude never answers. It only maps a question the rule parser couldn't handle onto
one of our intents and onto place ids that already exist on the map. Structured
outputs (a JSON schema whose id fields are enums of this map's ids) keep it from
introducing a place. The answer is then produced by the normal grounded pipeline
from map data.

Anthropic Python SDK, Messages API: `client.beta.messages.create` with
`output_config.format` (json_schema), `output_config.effort = "low"` for voice
latency, and the server-side refusal fallback (`fallbacks="default"`).
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass

try:
    import anthropic
except ImportError:  # the app runs without the SDK; the interpreter just stays off
    anthropic = None  # type: ignore[assignment]

log = logging.getLogger(__name__)

DEFAULT_MODEL = "claude-opus-5-5"
FALLBACK_BETA = "server-side-fallback-2026-07-01"
# Models that accept fallbacks="default" (Haiku 5.5 has no server-side fallback). Same list as
# app.touchspace.chat; other models are called without the fallback.
FALLBACK_MODELS = frozenset({"claude-opus-5-5", "claude-opus-5", "claude-sonnet-5-5", "claude-fable-5-1"})
MAX_TOKENS = 1024  # thinking counts against this; the JSON reply itself is tiny
INTENTS = ["overview", "list", "where", "nearby", "route", "whereami", "help", "unknown"]
TARGET_INTENTS = ("where", "nearby", "route")
NONE = "none"

SYSTEM = (
    "You convert a question about an indoor floor plan into a structured request for a navigation app "
    "used by blind and low-vision people. Do not answer the question.\n"
    "Intents: overview = describe the whole space; list = which places exist; where = location of one place; "
    "nearby = what is near a place; route = directions to a place (origin optional); whereami = the user's "
    "position; help = how to use the app; unknown = not about this map.\n"
    "Pick place ids only from the list you are given, or 'none'. If unsure, use intent 'unknown'."
)


@dataclass(frozen=True)
class ClaudeConfig:
    api_key: str | None
    model: str = DEFAULT_MODEL
    timeout_s: float = 10.0
    max_retries: int = 1

    @property
    def enabled(self) -> bool:
        return bool(self.api_key) and anthropic is not None

    @classmethod
    def from_env(cls) -> "ClaudeConfig":
        return cls(
            api_key=os.environ.get("ANTHROPIC_API_KEY") or None,
            model=os.environ.get("TOUCHSPACE_INTERPRETER_MODEL") or DEFAULT_MODEL,
        )


@dataclass(frozen=True)
class Interpretation:
    intent: str
    target_id: str | None
    origin_id: str | None


def response_schema(ids: list[str]) -> dict:
    """JSON schema for the reply: every field required, ids limited to this map."""
    choices = list(dict.fromkeys([*ids, NONE]))  # enum values must be unique
    return {
        "type": "object",
        "properties": {
            "intent": {"type": "string", "enum": INTENTS},
            "target_id": {"type": "string", "enum": choices},
            "origin_id": {"type": "string", "enum": choices},
        },
        "required": ["intent", "target_id", "origin_id"],
        "additionalProperties": False,
    }


class ClaudeInterpreter:
    def __init__(self, config: ClaudeConfig, http_client=None):
        """`http_client` (an httpx2.Client) is for tests; production uses the SDK's default client."""
        self.config = config
        self._client = None
        if config.enabled:
            self._client = anthropic.Anthropic(
                api_key=config.api_key,
                timeout=config.timeout_s,
                max_retries=config.max_retries,
                http_client=http_client,
            )

    @property
    def enabled(self) -> bool:
        return self._client is not None

    def interpret(self, question: str, places: list[tuple[str, str, str]], last_place_id: str | None) -> Interpretation | None:
        """places: (id, name, kind). Returns None when disabled, failing, refused, or unsure."""
        if self._client is None or not places:
            return None
        ids = [p[0] for p in places]
        listing = "\n".join(f"- {pid}: {name} ({kind})" for pid, name, kind in places)
        prompt = (
            f"Places on this map (id: name (kind)):\n{listing}\n"
            f"The previous answer was about: {last_place_id or 'nothing yet'}.\n"
            f"Question: {question}"
        )
        params = {}
        if self.config.model in FALLBACK_MODELS:
            params.update(betas=[FALLBACK_BETA], fallbacks="default")
        try:
            response = self._client.beta.messages.create(
                model=self.config.model,
                max_tokens=MAX_TOKENS,
                system=SYSTEM,
                messages=[{"role": "user", "content": prompt}],
                output_config={"effort": "low", "format": {"type": "json_schema", "schema": response_schema(ids)}},
                **params,
            )
        except anthropic.APIStatusError as exc:
            log.warning("Claude interpreter unavailable: HTTP %s (request %s)", exc.status_code, exc.request_id)
            return None
        except anthropic.APITimeoutError:
            log.warning("Claude interpreter timed out after %.0fs", self.config.timeout_s)
            return None
        except anthropic.APIConnectionError:
            log.warning("Claude interpreter unreachable")
            return None
        except anthropic.AnthropicError as exc:
            log.warning("Claude interpreter failed: %s", type(exc).__name__)
            return None

        # A refusal means the whole fallback chain declined; content may be empty or partial.
        if response.stop_reason in ("refusal", "max_tokens"):
            return None
        # After a fallback the served answer is the last text block.
        texts = [b.text for b in response.content if b.type == "text"]
        if not texts:
            return None
        try:
            data = json.loads(texts[-1])
        except ValueError:
            return None
        return _validated(data, ids)


def _validated(data: object, ids: list[str]) -> Interpretation | None:
    if not isinstance(data, dict):
        return None
    intent = data.get("intent")
    if intent not in INTENTS or intent == "unknown":
        return None

    def valid(v: object) -> str | None:
        return v if isinstance(v, str) and v in ids else None

    target, origin = valid(data.get("target_id")), valid(data.get("origin_id"))
    if intent in TARGET_INTENTS and target is None:
        return None
    return Interpretation(intent=intent, target_id=target, origin_id=origin)
