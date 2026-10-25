"""Claude only helps parse questions; answers stay grounded.

The Anthropic SDK is exercised end to end against an httpx2 MockTransport (the SDK is
built on httpx2), so no test touches the network.
"""

from __future__ import annotations

import json

import httpx2
import pytest
from fastapi.testclient import TestClient

from app.main import app, get_interpreter, get_store
from app.services.assistant import answer
from app.services.claude_interpreter import DEFAULT_MODEL, FALLBACK_BETA, ClaudeConfig, ClaudeInterpreter
from app.services.floorplan import process_map
from app.services.storage import MapStore

MESSAGES_URL = "https://api.anthropic.com/v1/messages"


def message(content: list[dict], stop_reason: str = "end_turn", **extra) -> dict:
    return {
        "id": "msg_test", "type": "message", "role": "assistant", "model": "claude-opus-5-5",
        "content": content, "stop_reason": stop_reason, "stop_sequence": None,
        "usage": {"input_tokens": 120, "output_tokens": 20}, **extra,
    }


def json_reply(reply: dict) -> dict:
    # Thinking is always on for Claude Opus 5.5; with the default display it comes back empty.
    return message([{"type": "thinking", "thinking": "", "signature": "sig"},
                    {"type": "text", "text": json.dumps(reply)}])


class FakeClaude:
    """Answers POST /v1/messages like the API would."""

    def __init__(self, body: dict | None = None, status: int = 200, error: Exception | None = None):
        self.body = body
        self.status = status
        self.error = error
        self.calls: list[httpx2.Request] = []

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        self.calls.append(request)
        if self.error is not None:
            raise self.error
        if self.status != 200:
            return httpx2.Response(self.status, json={"type": "error", "error": {"type": "api_error", "message": "nope"}})
        return httpx2.Response(200, json=self.body)


def interpreter(fake: FakeClaude, key: str | None = "test-key", model: str = DEFAULT_MODEL) -> ClaudeInterpreter:
    config = ClaudeConfig(api_key=key, model=model, max_retries=0)
    return ClaudeInterpreter(config, http_client=httpx2.Client(transport=httpx2.MockTransport(fake)))


@pytest.fixture(autouse=True)
def _default_base_url(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_BASE_URL", raising=False)


@pytest.fixture
def demo(demo_map):
    return process_map(demo_map).map


def test_rules_answer_without_calling_claude(demo):
    fake = FakeClaude(json_reply({"intent": "where", "target_id": "lm_exit", "origin_id": "none"}))
    r = answer(demo, "Where is the restroom?", interpreter=interpreter(fake))
    assert r.understood_by == "rules" and r.place_ids == ["lm_restroom"]
    assert fake.calls == []


def test_claude_maps_free_form_question_to_a_known_place(demo):
    fake = FakeClaude(json_reply({"intent": "route", "target_id": "lm_restroom", "origin_id": "none"}))
    r = answer(demo, "I really need to wash my hands, which way?", interpreter=interpreter(fake))
    assert r.understood_by == "claude"
    assert r.intent == "route" and r.route.found and r.route.destination_name == "Restroom"
    # The answer text still comes from the map, not from the model.
    assert r.answer.startswith("From Main Entrance to Restroom is about 12 meters.")


def test_request_uses_structured_output_limited_to_map_ids(demo):
    fake = FakeClaude(json_reply({"intent": "where", "target_id": "lm_exit", "origin_id": "none"}))
    answer(demo, "how do i leave this building", interpreter=interpreter(fake))
    (req,) = fake.calls
    assert req.method == "POST" and str(req.url).split("?")[0] == MESSAGES_URL
    # SDK 2.x sends the key as a bearer token (1.x used x-api-key).
    assert "test-key" in (req.headers.get("authorization", "") + req.headers.get("x-api-key", ""))
    assert "test-key" not in str(req.url)  # key stays out of URLs and logs
    assert FALLBACK_BETA in req.headers["anthropic-beta"]
    body = json.loads(req.content)
    assert body["model"] == "claude-opus-5-5"
    assert body["max_tokens"] >= 1024
    assert body["fallbacks"] == "default"
    # Claude Opus 5.5: thinking is always on; sending thinking or sampling params is a 400.
    assert "thinking" not in body and "temperature" not in body
    assert body["output_config"]["effort"] == "low"
    fmt = body["output_config"]["format"]
    assert fmt["type"] == "json_schema"
    schema = fmt["schema"]
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == {"intent", "target_id", "origin_id"}
    assert set(schema["properties"]["target_id"]["enum"]) >= {"lm_restroom", "lm_exit", "none"}
    assert "unknown" in schema["properties"]["intent"]["enum"]
    assert "Do not answer the question" in body["system"]
    (msg,) = body["messages"]
    assert msg["role"] == "user" and "how do i leave this building" in msg["content"]
    assert "output_format" not in body and "tool_choice" not in body


def test_no_fallback_for_models_without_server_side_fallback(demo):
    fake = FakeClaude(json_reply({"intent": "where", "target_id": "lm_exit", "origin_id": "none"}))
    answer(demo, "how do i leave this building", interpreter=interpreter(fake, model="claude-haiku-5-5"))
    (req,) = fake.calls
    body = json.loads(req.content)
    assert body["model"] == "claude-haiku-5-5" and "fallbacks" not in body
    assert "anthropic-beta" not in req.headers


def test_answer_after_a_server_side_fallback_is_used(demo):
    reply = {"intent": "where", "target_id": "lm_elevator", "origin_id": "none"}
    body = message([
        {"type": "fallback", "from": {"model": "claude-opus-5-5"}, "to": {"model": "claude-opus-4-8"},
         "trigger": {"type": "refusal"}},
        {"type": "text", "text": json.dumps(reply)},
    ], model="claude-opus-4-8")
    r = answer(demo, "I can't do stairs, how do I go up a floor?", interpreter=interpreter(FakeClaude(body)))
    assert r.understood_by == "claude" and r.place_ids == ["lm_elevator"]


@pytest.mark.parametrize("reply", [
    {"intent": "where", "target_id": "lm_made_up", "origin_id": "none"},  # id not on the map
    {"intent": "unknown", "target_id": "none", "origin_id": "none"},
    {"intent": "where", "target_id": "none", "origin_id": "none"},  # where/nearby/route need a target
    {"intent": "teleport", "target_id": "lm_exit", "origin_id": "none"},
])
def test_unusable_interpretations_fall_back_to_rules(demo, reply):
    r = answer(demo, "what's the weather", interpreter=interpreter(FakeClaude(json_reply(reply))))
    assert r.understood_by == "rules" and r.intent == "unknown"


@pytest.mark.parametrize("fake", [
    FakeClaude(status=500),
    FakeClaude(status=529),
    FakeClaude(status=401),
    FakeClaude(status=429),
    FakeClaude(status=400),
    FakeClaude(error=httpx2.ConnectError("offline")),
    FakeClaude(error=httpx2.ReadTimeout("slow")),
    FakeClaude(message([{"type": "text", "text": "not json"}])),
    FakeClaude(message([{"type": "text", "text": "[1, 2]"}])),
    FakeClaude(message([])),
], ids=["500", "529", "401", "429", "400", "connect", "timeout", "bad-json", "not-object", "empty"])
def test_provider_failures_fall_back_to_rules(demo, fake):
    r = answer(demo, "what's the weather", interpreter=interpreter(fake))
    assert r.understood_by == "rules" and r.intent == "unknown"
    assert len(fake.calls) == 1


def test_refusal_is_treated_as_unavailable(demo):
    # Even a schema-shaped partial must not be used once the whole fallback chain refused.
    partial = json.dumps({"intent": "where", "target_id": "lm_exit", "origin_id": "none"})
    body = message([{"type": "text", "text": partial}], stop_reason="refusal",
                   stop_details={"type": "refusal", "category": None, "explanation": None})
    r = answer(demo, "what's the weather", interpreter=interpreter(FakeClaude(body)))
    assert r.understood_by == "rules" and r.intent == "unknown"


def test_truncated_reply_is_not_used(demo):
    partial = json.dumps({"intent": "where", "target_id": "lm_exit", "origin_id": "none"})
    body = message([{"type": "text", "text": partial}], stop_reason="max_tokens")
    r = answer(demo, "what's the weather", interpreter=interpreter(FakeClaude(body)))
    assert r.understood_by == "rules"


def test_disabled_claude_is_never_called(demo):
    fake = FakeClaude(json_reply({"intent": "where", "target_id": "lm_exit", "origin_id": "none"}))
    disabled = interpreter(fake, key=None)
    assert disabled.enabled is False
    r = answer(demo, "what's the weather", interpreter=disabled)
    assert r.intent == "unknown" and fake.calls == []


def test_config_from_env(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("TOUCHSPACE_INTERPRETER_MODEL", raising=False)
    off = ClaudeConfig.from_env()
    assert off.api_key is None and off.enabled is False and off.model == DEFAULT_MODEL == "claude-opus-5-5"
    monkeypatch.setenv("ANTHROPIC_API_KEY", "env-key")
    monkeypatch.setenv("TOUCHSPACE_INTERPRETER_MODEL", "claude-other")
    on = ClaudeConfig.from_env()
    assert on.api_key == "env-key" and on.enabled is True and on.model == "claude-other"
    assert on.timeout_s <= 15


def test_ask_api_uses_configured_interpreter(tmp_path):
    store = MapStore(tmp_path)
    fake = FakeClaude(json_reply({"intent": "where", "target_id": "lm_elevator", "origin_id": "none"}))
    app.dependency_overrides[get_store] = lambda: store
    app.dependency_overrides[get_interpreter] = lambda: interpreter(fake)
    try:
        client = TestClient(app)
        map_id = client.post("/api/demo").json()["map"]["id"]
        body = client.post(f"/api/maps/{map_id}/ask", json={"question": "I can't do stairs, how do I go up a floor?"}).json()
        assert body["understood_by"] == "claude" and body["place_ids"] == ["lm_elevator"]
        features = client.get("/api/health").json()["features"]
        assert features["claude"] is True and "gemini" not in features
    finally:
        app.dependency_overrides.pop(get_store, None)


def test_health_reports_claude_off_without_a_key():
    features = TestClient(app).get("/api/health").json()["features"]
    assert features["claude"] is False and "gemini" not in features
