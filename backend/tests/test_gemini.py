"""Gemini only helps parse questions; answers stay grounded. Tested with a fake transport."""

from __future__ import annotations

import json

import httpx
import pytest
from fastapi.testclient import TestClient

from app.main import app, get_interpreter, get_store
from app.services.assistant import answer
from app.services.floorplan import process_map
from app.services.gemini import GeminiConfig, GeminiInterpreter
from app.services.storage import MapStore


class FakeGemini:
    def __init__(self, reply: dict | None = None, status: int = 200):
        self.reply = reply
        self.status = status
        self.calls: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        if self.status != 200:
            return httpx.Response(self.status, json={"error": {"message": "nope"}})
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": json.dumps(self.reply)}]}}]})


def interpreter(fake: FakeGemini, key: str | None = "test-key") -> GeminiInterpreter:
    return GeminiInterpreter(GeminiConfig(api_key=key, model="gemini-test"), transport=httpx.MockTransport(fake))


@pytest.fixture
def demo(demo_map):
    return process_map(demo_map).map


def test_rules_answer_without_calling_gemini(demo):
    fake = FakeGemini({"intent": "where", "target_id": "lm_exit", "origin_id": "none"})
    r = answer(demo, "Where is the restroom?", interpreter=interpreter(fake))
    assert r.understood_by == "rules" and r.place_ids == ["lm_restroom"]
    assert fake.calls == []


def test_gemini_maps_free_form_question_to_a_known_place(demo):
    fake = FakeGemini({"intent": "route", "target_id": "lm_restroom", "origin_id": "none"})
    r = answer(demo, "I really need to wash my hands, which way?", interpreter=interpreter(fake))
    assert r.understood_by == "gemini"
    assert r.intent == "route" and r.route.found and r.route.destination_name == "Restroom"
    # The answer text still comes from the map, not from the model.
    assert r.answer.startswith("From Main Entrance to Restroom is about 12 meters.")


def test_request_format_restricts_model_to_map_ids(demo):
    fake = FakeGemini({"intent": "where", "target_id": "lm_exit", "origin_id": "none"})
    answer(demo, "how do i leave this building", interpreter=interpreter(fake))
    (req,) = fake.calls
    assert req.url.path.endswith("/models/gemini-test:generateContent")
    assert req.headers["x-goog-api-key"] == "test-key"
    assert "key=" not in str(req.url)  # key stays out of URLs and logs
    body = json.loads(req.content)
    schema = body["generationConfig"]["responseSchema"]
    assert body["generationConfig"]["responseMimeType"] == "application/json"
    assert set(schema["properties"]["target_id"]["enum"]) >= {"lm_restroom", "lm_exit", "none"}
    assert "Do not answer the question" in body["contents"][0]["parts"][0]["text"]


@pytest.mark.parametrize("reply", [
    {"intent": "where", "target_id": "lm_made_up", "origin_id": "none"},  # id not on the map
    {"intent": "unknown", "target_id": "none", "origin_id": "none"},
    {"intent": "where", "target_id": "none", "origin_id": "none"},
])
def test_unusable_interpretations_fall_back_to_rules(demo, reply):
    r = answer(demo, "what's the weather", interpreter=interpreter(FakeGemini(reply)))
    assert r.understood_by == "rules" and r.intent == "unknown"


def test_gemini_errors_fall_back_to_rules(demo):
    r = answer(demo, "what's the weather", interpreter=interpreter(FakeGemini(status=500)))
    assert r.understood_by == "rules" and r.intent == "unknown"


def test_disabled_gemini_is_never_called(demo):
    fake = FakeGemini({"intent": "where", "target_id": "lm_exit", "origin_id": "none"})
    r = answer(demo, "what's the weather", interpreter=interpreter(fake, key=None))
    assert r.intent == "unknown" and fake.calls == []


def test_ask_api_uses_configured_interpreter(tmp_path):
    store = MapStore(tmp_path)
    fake = FakeGemini({"intent": "where", "target_id": "lm_elevator", "origin_id": "none"})
    app.dependency_overrides[get_store] = lambda: store
    app.dependency_overrides[get_interpreter] = lambda: interpreter(fake)
    client = TestClient(app)
    map_id = client.post("/api/demo").json()["map"]["id"]
    body = client.post(f"/api/maps/{map_id}/ask", json={"question": "I can't do stairs, how do I go up a floor?"}).json()
    assert body["understood_by"] == "gemini" and body["place_ids"] == ["lm_elevator"]
    assert client.get("/api/health").json()["features"]["gemini"] is True
    app.dependency_overrides.pop(get_store)
