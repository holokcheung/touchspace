"""Cartesia integration, tested against a fake transport (no network, no credits)."""

from __future__ import annotations

import json
import os

import httpx
import pytest
from fastapi.testclient import TestClient

from app.main import _load_dotenv, app, get_voice
from app.services.voice import API_VERSION, CartesiaVoice, VoiceConfig

FAKE_MP3 = b"ID3\x04\x00fake-mp3-bytes"


class FakeCartesia:
    def __init__(self, *, status: int = 200, voices=None, fail: Exception | None = None):
        self.calls: list[httpx.Request] = []
        self.status = status
        self.voices = voices if voices is not None else {"data": [
            {"id": "voice-fr", "language": "fr"}, {"id": "voice-en", "language": "en"}]}
        self.fail = fail

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        if self.fail:
            raise self.fail
        if self.status != 200:
            return httpx.Response(self.status, text="nope")
        if request.url.path == "/voices":
            return httpx.Response(200, json=self.voices)
        if request.url.path == "/tts/bytes":
            return httpx.Response(200, content=FAKE_MP3, headers={"Content-Type": "audio/mpeg"})
        if request.url.path == "/stt":
            return httpx.Response(200, json={"type": "transcript", "text": " Where is the restroom? ", "duration": 1.4})
        return httpx.Response(404)


def make_voice(fake: FakeCartesia | None = None, *, key: str | None = "sk_car_test", voice_id: str | None = None):
    transport = httpx.MockTransport(fake) if fake else None
    return CartesiaVoice(VoiceConfig(api_key=key, voice_id=voice_id, tts_model="sonic-3.6"), transport=transport)


@pytest.fixture
def client_with():
    def make(voice: CartesiaVoice) -> TestClient:
        app.dependency_overrides[get_voice] = lambda: voice
        return TestClient(app)
    yield make
    app.dependency_overrides.clear()


def test_tts_request_matches_cartesia_api(client_with):
    fake = FakeCartesia()
    r = client_with(make_voice(fake, voice_id="voice-123")).post("/api/tts", json={"text": "The restroom   is north."})
    assert r.status_code == 200
    assert r.headers["content-type"] == "audio/mpeg"
    assert r.content == FAKE_MP3
    (req,) = fake.calls
    assert req.method == "POST" and str(req.url) == "https://api.cartesia.ai/tts/bytes"
    assert req.headers["authorization"] == "Bearer sk_car_test"
    assert req.headers["cartesia-version"] == API_VERSION
    body = json.loads(req.content)
    assert body == {
        "model_id": "sonic-3.6",
        "transcript": "The restroom is north.",
        "voice": {"id": "voice-123"},
        "output_format": {"container": "mp3", "sample_rate": 44100, "bit_rate": 128000},
        "language": "en",
    }


def test_speed_is_sent_as_generation_config(client_with):
    fake = FakeCartesia()
    client_with(make_voice(fake, voice_id="v")).post("/api/tts", json={"text": "Slowly.", "speed": 0.8})
    assert json.loads(fake.calls[0].content)["generation_config"] == {"speed": 0.8}


def test_repeated_text_is_served_from_cache(client_with):
    fake = FakeCartesia()
    client = client_with(make_voice(fake, voice_id="v"))
    for _ in range(3):
        assert client.post("/api/tts", json={"text": "Replay me."}).status_code == 200
    assert len(fake.calls) == 1


def test_default_voice_is_first_english_voice():
    fake = FakeCartesia()
    voice = make_voice(fake)
    voice.synthesize("Hello.")
    assert [c.url.path for c in fake.calls] == ["/voices", "/tts/bytes"]
    assert json.loads(fake.calls[1].content)["voice"] == {"id": "voice-en"}
    voice.synthesize("Again.")  # voice lookup is remembered
    assert [c.url.path for c in fake.calls].count("/voices") == 1


def test_voice_list_as_plain_array_is_accepted():
    fake = FakeCartesia(voices=[{"id": "only-en", "language": "en-US"}])
    voice = make_voice(fake)
    assert voice.voice_id() == "only-en"


def test_not_configured_returns_503_and_health_says_so(client_with):
    client = client_with(make_voice(key=None))
    r = client.post("/api/tts", json={"text": "hi"})
    assert r.status_code == 503 and r.json()["error"]["code"] == "voice_unavailable"
    assert client.get("/api/health").json()["features"]["cartesia"] is False


@pytest.mark.parametrize("status,needle", [(401, "rejected the API key"), (429, "rate limit"), (500, "error (500)")])
def test_cartesia_errors_become_clear_503s(client_with, status, needle):
    r = client_with(make_voice(FakeCartesia(status=status), voice_id="v")).post("/api/tts", json={"text": "hi"})
    assert r.status_code == 503 and needle in r.json()["error"]["message"]


def test_network_failure_is_a_503(client_with):
    fake = FakeCartesia(fail=httpx.ConnectError("down"))
    r = client_with(make_voice(fake, voice_id="v")).post("/api/tts", json={"text": "hi"})
    assert r.status_code == 503 and "Could not reach Cartesia" in r.json()["error"]["message"]


def test_text_limits(client_with):
    client = client_with(make_voice(FakeCartesia(), voice_id="v"))
    assert client.post("/api/tts", json={"text": ""}).status_code == 422
    assert client.post("/api/tts", json={"text": "x" * 2001}).status_code == 422
    assert client.post("/api/tts", json={"text": "   "}).status_code == 422  # whitespace only


def test_stt_sends_ink_whisper_multipart(client_with):
    fake = FakeCartesia()
    r = client_with(make_voice(fake)).post("/api/stt", files={"file": ("q.webm", b"\x1aE\xdf\xa3audio", "audio/webm")})
    assert r.status_code == 200 and r.json() == {"text": "Where is the restroom?"}
    (req,) = fake.calls
    assert str(req.url) == "https://api.cartesia.ai/stt"
    assert req.headers["authorization"] == "Bearer sk_car_test"
    assert req.headers["content-type"].startswith("multipart/form-data")
    body = req.content
    assert b'name="model"' in body and b"ink-whisper" in body
    assert b'name="file"; filename="q.webm"' in body


def test_stt_rejects_empty_audio(client_with):
    r = client_with(make_voice(FakeCartesia())).post("/api/stt", files={"file": ("q.webm", b"", "audio/webm")})
    assert r.status_code == 422


def test_dotenv_loader_does_not_override_real_environment(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text('# comment\nTS_TEST_A="from-file"\nTS_TEST_B=from-file\nTS_TEST_EMPTY=\n')
    monkeypatch.setenv("TS_TEST_B", "from-shell")
    monkeypatch.delenv("TS_TEST_A", raising=False)
    _load_dotenv(env)
    assert os.environ["TS_TEST_A"] == "from-file"
    assert os.environ["TS_TEST_B"] == "from-shell"
    assert "TS_TEST_EMPTY" not in os.environ
    monkeypatch.delenv("TS_TEST_A")
