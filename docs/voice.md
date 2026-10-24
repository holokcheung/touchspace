# Voice: Cartesia with a browser fallback

TouchSpace speaks and listens through [Cartesia](https://cartesia.ai) when the server has an API key, and through the browser's built-in speech otherwise. Voice always works, and the paid service is optional.

## Setup

1. Create an API key at https://play.cartesia.ai (API keys page).
2. Copy `.env.example` to `.env` in the repo root. `.env` is gitignored, so the key never reaches GitHub. Then set:
   ```
   CARTESIA_API_KEY=sk_car_...
   CARTESIA_VOICE_ID=          # optional; otherwise the first English voice on your account
   CARTESIA_TTS_MODEL=         # optional; default sonic-3.6
   ```
3. Restart the backend. `GET /api/health` should report `"cartesia": true`.

Never put the key in frontend code or paste it into chat. The browser only talks to our backend.

## Backend endpoints

| Endpoint | Cartesia call | Returns |
| --- | --- | --- |
| `POST /api/tts` `{"text", "speed"?}` | `POST /tts/bytes`, model `sonic-3.6`, MP3 44.1 kHz / 128 kbps | `audio/mpeg` |
| `POST /api/stt` multipart `file` | `POST /stt`, model `ink-whisper`, `language=en` | `{"text": "..."}` |

- Both send `Authorization: Bearer <key>` and `Cartesia-Version: 2026-08-14`.
- If Cartesia isn't configured or fails (bad key, rate limit, network), both return **503** with `error.code = "voice_unavailable"` and a readable message. The frontend treats that as "use the browser instead".
- Speech for the same text is cached in memory (64 entries), so **Replay** costs nothing.

Code: `backend/app/services/voice.py`. Tests use a fake transport and never call Cartesia: `backend/tests/test_voice.py`.

## Frontend helpers (`frontend/src/lib/voice.ts`)

```ts
import { speak, stopSpeaking, createListener } from "../lib/voice";

const handle = await speak(answerText);   // handle.engine: "cartesia" | "browser" | "none"
handle.stop();                            // or stopSpeaking()

const listener = await createListener({
  onResult: (text) => ask(text),
  onError: (msg) => showError(msg),      // always offer the text box too
  onStateChange: (listening) => setListening(listening),
});
await listener.start();                   // push to talk...
await listener.stop();                    // ...release: Cartesia transcribes the recording
```

- **Speaking:** Cartesia when available. It falls back to `speechSynthesis` if Cartesia is off, errors, or the browser blocks audio.
- **Listening:** records with `MediaRecorder` and transcribes with Cartesia when available. Otherwise it uses the browser's `SpeechRecognition` (Chrome and Edge). With neither, it says so, so the UI can point to typing.

`ReadAloud` (`frontend/src/components/ReadAloud.tsx`) is a ready-made Read aloud / Stop button with a live status line. It's used on the floor-plan and 3D pages to read their text descriptions aloud.

## For the Voice Explorer (Phase 4)

Use `speak()` for answers, with a Replay button calling `speak()` again, which hits the cache. Use `createListener()` for the microphone button. Don't call Cartesia directly from the frontend, and don't add a second TTS path.
