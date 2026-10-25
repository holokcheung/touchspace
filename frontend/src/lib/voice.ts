/**
 * Speech for TouchSpace. Prefers Cartesia (through our backend, so the API key stays
 * secret) and falls back to the browser's built-in speech when Cartesia is not
 * configured, not reachable, or the browser blocks audio.
 *
 *   const handle = await speak("The restroom is north of the hallway.");
 *   handle.stop();            // stop early
 *   await handle.done;        // resolves when speech ends or is stopped
 *
 *   const listener = createListener({ onResult: (text) => ... });
 *   await listener.start();   // ...user talks...
 *   await listener.stop();    // Cartesia: transcribes the recording; browser: ends recognition
 */

const BASE = import.meta.env.VITE_API_BASE ?? "";

export type VoiceEngine = "cartesia" | "browser" | "none";

export interface SpeechHandle {
  engine: VoiceEngine;
  done: Promise<void>;
  stop: () => void;
}

let cartesiaState: Promise<boolean> | null = null;
let current: SpeechHandle | null = null;
let speechGeneration = 0;
const audioCache = new Map<string, string>(); // text -> object URL, so Replay is instant and free

/** Whether the server has Cartesia configured. Cached for the page's lifetime. */
export function cartesiaAvailable(): Promise<boolean> {
  cartesiaState ??= fetch(`${BASE}/api/health`)
    .then((r) => (r.ok ? r.json() : null))
    .then((h) => Boolean(h?.features?.cartesia))
    .catch(() => false);
  return cartesiaState;
}

export function browserSpeechAvailable(): boolean {
  return (
    typeof window !== "undefined" &&
    "speechSynthesis" in window &&
    typeof SpeechSynthesisUtterance !== "undefined"
  );
}

export function stopSpeaking(): void {
  speechGeneration++;
  current?.stop();
  current = null;
}

async function cartesiaAudioUrl(text: string, speed: number): Promise<string> {
  const key = `${speed}|${text}`;
  const cached = audioCache.get(key);
  if (cached) return cached;
  const res = await fetch(`${BASE}/api/tts`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text, speed }),
  });
  if (res.status === 503) cartesiaState = Promise.resolve(false); // not configured: stop asking
  if (!res.ok) throw new Error(`Cartesia speech failed (${res.status}).`);
  const url = URL.createObjectURL(await res.blob());
  audioCache.set(key, url);
  return url;
}

/** Starts playback and resolves once audio is playing. Rejects if the browser blocks it. */
async function playUrl(url: string): Promise<SpeechHandle> {
  const audio = new Audio(url);
  let finish: () => void = () => {};
  const done = new Promise<void>((resolve) => {
    finish = resolve;
  });
  audio.addEventListener("ended", () => finish());
  audio.addEventListener("error", () => finish());
  await audio.play();
  return {
    engine: "cartesia",
    done,
    stop: () => {
      audio.pause();
      finish();
    },
  };
}

function speakWithBrowser(text: string, speed: number): SpeechHandle {
  if (!browserSpeechAvailable()) {
    return { engine: "none", done: Promise.resolve(), stop: () => {} };
  }
  const synth = window.speechSynthesis;
  synth.cancel();
  const utterance = new SpeechSynthesisUtterance(text);
  utterance.rate = speed;
  utterance.lang = "en-US";
  let finish: () => void = () => {};
  const done = new Promise<void>((resolve) => {
    finish = resolve;
    utterance.onend = () => resolve();
    utterance.onerror = () => resolve();
  });
  synth.speak(utterance);
  return {
    engine: "browser",
    done,
    stop: () => {
      synth.cancel();
      finish();
    },
  };
}

/** Speak text aloud, stopping anything already playing. Never throws; check `engine`. */
export async function speak(
  text: string,
  opts: { speed?: number } = {},
): Promise<SpeechHandle> {
  stopSpeaking();
  const generation = speechGeneration;
  const empty: SpeechHandle = {
    engine: "none",
    done: Promise.resolve(),
    stop: () => {},
  };
  const speed = opts.speed ?? 1;
  const clean = text.replace(/\s+/g, " ").trim().slice(0, 2000);
  if (!clean)
    return { engine: "none", done: Promise.resolve(), stop: () => {} };

  if (await cartesiaAvailable()) {
    try {
      const url = await cartesiaAudioUrl(clean, speed);
      if (generation !== speechGeneration) return empty;
      const handle = await playUrl(url);
      if (generation !== speechGeneration) {
        handle.stop();
        return empty;
      }
      current = handle;
      return current;
    } catch {
      // Network error, quota, or autoplay block: fall through to the browser voice.
    }
  }
  if (generation !== speechGeneration) return empty;
  current = speakWithBrowser(clean, speed);
  return current;
}

// --------------------------------------------------------------------------- listening

export interface Listener {
  engine: VoiceEngine;
  start: () => Promise<void>;
  stop: () => Promise<void>;
  cancel: () => void;
}

interface ListenerCallbacks {
  onResult: (text: string) => void;
  onError?: (message: string) => void;
  onStateChange?: (listening: boolean) => void;
}

type BrowserRecognition = {
  lang: string;
  interimResults: boolean;
  maxAlternatives: number;
  start: () => void;
  stop: () => void;
  onresult:
    | ((e: { results: ArrayLike<ArrayLike<{ transcript: string }>> }) => void)
    | null;
  onerror: ((e: { error: string }) => void) | null;
  onend: (() => void) | null;
};

function browserRecognitionCtor(): (new () => BrowserRecognition) | null {
  const w = window as unknown as Record<string, unknown>;
  return (w.SpeechRecognition ?? w.webkitSpeechRecognition ?? null) as
    (new () => BrowserRecognition) | null;
}

export function browserRecognitionAvailable(): boolean {
  return typeof window !== "undefined" && browserRecognitionCtor() !== null;
}

function recordingAvailable(): boolean {
  return (
    typeof window !== "undefined" &&
    typeof MediaRecorder !== "undefined" &&
    Boolean(navigator.mediaDevices?.getUserMedia)
  );
}

/**
 * Push-to-talk listener. Uses Cartesia transcription when the server supports it and the
 * browser can record; otherwise browser speech recognition. Callers must always offer typing too.
 */
export async function createListener(cb: ListenerCallbacks): Promise<Listener> {
  if ((await cartesiaAvailable()) && recordingAvailable()) {
    let recorder: MediaRecorder | null = null;
    let chunks: Blob[] = [];
    let cancelled = false;
    return {
      engine: "cartesia",
      cancel: () => {
        cancelled = true;
        if (recorder) {
          if (recorder.state !== "inactive") recorder.stop();
          recorder.stream.getTracks().forEach((t) => t.stop());
          recorder = null;
        }
      },
      start: async () => {
        let stream: MediaStream | null = null;
        try {
          stream = await navigator.mediaDevices.getUserMedia({
            audio: true,
          });
          if (cancelled) {
            stream.getTracks().forEach((t) => t.stop());
            return;
          }
          chunks = [];
          recorder = new MediaRecorder(stream);
          recorder.ondataavailable = (e) => e.data.size && chunks.push(e.data);
          recorder.start();
          cb.onStateChange?.(true);
        } catch {
          stream?.getTracks().forEach((track) => track.stop());
          cb.onError?.(
            "Microphone access was blocked. You can type your question instead.",
          );
        }
      },
      stop: async () => {
        const rec = recorder;
        if (!rec) return;
        recorder = null;
        const stopped = new Promise<void>(
          (resolve) => (rec.onstop = () => resolve()),
        );
        rec.stop();
        rec.stream.getTracks().forEach((t) => t.stop());
        await stopped;
        if (cancelled) return;
        cb.onStateChange?.(false);
        const blob = new Blob(chunks, { type: rec.mimeType || "audio/webm" });
        const ext = blob.type.includes("mp4")
          ? "mp4"
          : blob.type.includes("ogg")
            ? "ogg"
            : "webm";
        const form = new FormData();
        form.append("file", blob, `question.${ext}`);
        try {
          const res = await fetch(`${BASE}/api/stt`, {
            method: "POST",
            body: form,
          });
          if (!res.ok) throw new Error(String(res.status));
          const { text } = await res.json();
          if (cancelled) return;
          if (text) cb.onResult(text);
          else
            cb.onError?.(
              "No speech was detected. Try again or type your question.",
            );
        } catch {
          cb.onError?.(
            "Could not transcribe the recording. You can type your question instead.",
          );
        }
      },
    };
  }

  const Ctor = browserRecognitionAvailable() ? browserRecognitionCtor() : null;
  if (Ctor) {
    const rec = new Ctor();
    rec.lang = "en-US";
    rec.interimResults = false;
    rec.maxAlternatives = 1;
    rec.onresult = (e) => {
      const text = e.results[0]?.[0]?.transcript;
      if (text) cb.onResult(text);
    };
    rec.onerror = (e) =>
      cb.onError?.(
        e.error === "not-allowed"
          ? "Microphone access was blocked. You can type your question instead."
          : "Speech recognition failed. You can type your question instead.",
      );
    rec.onend = () => cb.onStateChange?.(false);
    return {
      engine: "browser",
      start: async () => {
        rec.start();
        cb.onStateChange?.(true);
      },
      stop: async () => rec.stop(),
      cancel: () => {
        rec.onresult = null;
        rec.onerror = null;
        rec.onend = null;
        try {
          rec.stop();
        } catch {
          /* already stopped */
        }
      },
    };
  }

  return {
    engine: "none",
    start: async () =>
      cb.onError?.(
        "Voice input is not available in this browser. Please type your question.",
      ),
    stop: async () => {},
    cancel: () => {},
  };
}
