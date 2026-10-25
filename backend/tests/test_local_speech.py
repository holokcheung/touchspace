from __future__ import annotations

import io
from pathlib import Path
import subprocess
import wave

import pytest
from fastapi.testclient import TestClient

from app.main import app, get_local_speech, get_voice
from app.services.local_speech import LocalSpeech
from app.services.voice import VoiceUnavailable


def wav(frames=3200, level=900, rate=16000):
    data = io.BytesIO()
    with wave.open(data, 'wb') as output:
        output.setparams((1, 2, rate, frames, 'NONE', 'not compressed'))
        output.writeframes(int(level).to_bytes(2, 'little', signed=True) * frames)
    return data.getvalue()


def configured(tmp_path):
    model = tmp_path / 'model.bin'
    model.write_bytes(b'model')
    executable = tmp_path / 'whisper-cli'
    executable.write_text('placeholder')
    return LocalSpeech(str(executable), model)


def test_local_transcription_runs_without_shell_and_removes_recordings(tmp_path, monkeypatch):
    speech = configured(tmp_path)
    temporary = []
    def infer(arguments, **options):
        assert options['check'] is True and options['timeout'] == 40
        assert not options.get('shell')
        assert '--no-gpu' in arguments and arguments[0] == speech.executable
        source = Path(arguments[arguments.index('--file')+1])
        assert source.read_bytes() == wav()
        temporary.append(source.parent)
        Path(arguments[arguments.index('--output-file')+1]+'.txt').write_text('Where is Reception desk?\n')
    monkeypatch.setattr(subprocess, 'run', infer)
    assert speech.transcribe(wav()) == 'Where is Reception desk?'
    assert all(not path.exists() for path in temporary)


@pytest.mark.parametrize('audio', [b'', b'not a wave', wav(level=0), wav(frames=100), wav(rate=48000)])
def test_invalid_or_silent_audio_never_runs_a_model(tmp_path, monkeypatch, audio):
    speech = configured(tmp_path)
    monkeypatch.setattr(subprocess, 'run', lambda *_args, **_kwargs: pytest.fail('Invalid audio must not run a process'))
    with pytest.raises(ValueError):
        speech.transcribe(audio)


def test_model_failure_is_bounded_and_recordings_are_removed(tmp_path, monkeypatch):
    speech = configured(tmp_path)
    temporary = []
    def timeout(arguments, **_options):
        temporary.append(Path(arguments[arguments.index('--file')+1]).parent)
        raise subprocess.TimeoutExpired(arguments, 40)
    monkeypatch.setattr(subprocess, 'run', timeout)
    for _ in range(2):
        with pytest.raises(VoiceUnavailable, match='could not process'):
            speech.transcribe(wav())
    assert all(not path.exists() for path in temporary)


def test_local_only_never_calls_a_cloud_provider_even_when_unavailable(tmp_path):
    class Cloud:
        def transcribe(self, *_args):
            pytest.fail('local_only must never fall back to a cloud provider')
    app.dependency_overrides[get_voice] = Cloud
    app.dependency_overrides[get_local_speech] = lambda: LocalSpeech('/missing/cli', tmp_path/'absent-model')
    try:
        response = TestClient(app).post('/api/stt', data={'local_only':'true'}, files={'file':('question.wav',wav(),'audio/wav')})
        assert response.status_code == 503
        assert 'Local transcription is not configured' in response.json()['error']['message']
    finally:
        app.dependency_overrides.clear()


def test_local_only_route_uses_the_local_service(tmp_path, monkeypatch):
    speech = configured(tmp_path)
    monkeypatch.setattr(speech, 'transcribe', lambda audio: 'Where is the reception desk?' if audio == wav() else '')
    app.dependency_overrides[get_local_speech] = lambda: speech
    try:
        response = TestClient(app).post('/api/stt', data={'local_only':'true'}, files={'file':('question.wav',wav(),'audio/wav')})
        assert response.status_code == 200
        assert response.json() == {'text':'Where is the reception desk?'}
    finally:
        app.dependency_overrides.clear()
