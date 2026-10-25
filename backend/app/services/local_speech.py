"""Optional offline Whisper transcription for simulator recordings.

Uses an explicitly installed whisper.cpp CLI/model. No network calls, shell
commands, transcript logging, or persistent recording files are involved.
"""
from __future__ import annotations

import io
import math
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
import wave
from array import array

from app.services.voice import MAX_STT_BYTES, VoiceUnavailable


class LocalSpeech:
    def __init__(self, executable: str | None = None, model: Path | None = None):
        self.executable = executable or os.environ.get("TOUCHSPACE_WHISPER_CLI") or shutil.which("whisper-cli")
        default = Path(__file__).resolve().parents[2] / "data/speech/ggml-tiny.en.bin"
        self.model = model or Path(os.environ.get("TOUCHSPACE_WHISPER_MODEL") or default)
        self._slot = threading.BoundedSemaphore(1)

    @property
    def enabled(self) -> bool:
        return bool(self.executable and Path(self.executable).is_file() and self.model.is_file())

    def transcribe(self, audio: bytes) -> str:
        if not self.enabled:
            raise VoiceUnavailable("Local transcription is not configured. Install whisper.cpp and a model on the TouchSpace server.")
        if not audio or len(audio) > MAX_STT_BYTES:
            raise ValueError("Recording must be nonempty and at most 10 MB.")
        try:
            with wave.open(io.BytesIO(audio), "rb") as recording:
                if (recording.getnchannels(), recording.getsampwidth(), recording.getframerate()) != (1, 2, 16000):
                    raise ValueError("Local transcription requires mono 16 kHz, 16-bit PCM WAV audio.")
                frames = recording.getnframes()
                if not 1600 <= frames <= 16000 * 60:
                    raise ValueError("Record between 0.1 and 60 seconds of speech.")
                samples = array("h", recording.readframes(frames))
                if len(samples) != frames:
                    raise ValueError("The WAV recording is incomplete.")
        except (wave.Error, EOFError) as exc:
            raise ValueError("The recording is not a valid PCM WAV file.") from exc
        rms = math.sqrt(sum(sample * sample for sample in samples) / len(samples))
        if rms < 30:
            raise ValueError("Microphone audio is silent. Check Simulator I/O → Audio Input and Mac microphone access, then try again.")
        if not self._slot.acquire(blocking=False):
            raise VoiceUnavailable("Local transcription is busy. Try again in a moment.")
        try:
            with tempfile.TemporaryDirectory(prefix="touchspace-speech-") as folder:
                source = Path(folder) / "question.wav"
                output = Path(folder) / "answer"
                source.write_bytes(audio)
                try:
                    subprocess.run(
                        [str(self.executable), "--model", str(self.model), "--file", str(source),
                         "--language", "en", "--threads", "4", "--no-gpu", "--no-prints",
                         "--output-txt", "--output-file", str(output)],
                        check=True, timeout=40, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    )
                    transcript = output.with_suffix(".txt").read_text().strip()
                except (OSError, subprocess.SubprocessError) as exc:
                    raise VoiceUnavailable("The local speech model could not process this recording.") from exc
                if not transcript or transcript.lower() in {"[blank_audio]", "[silence]", "(silence)"}:
                    raise ValueError("No speech was detected. Check the microphone input and try again.")
                if len(transcript) > 4000:
                    raise ValueError("The spoken question is too long.")
                return transcript
        finally:
            self._slot.release()
