import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// voice.ts caches whether Cartesia is available, so each test loads a fresh copy.
async function freshVoice() {
  vi.resetModules();
  return import("../lib/voice");
}

const spoken: string[] = [];
const played: string[] = [];

class FakeUtterance {
  rate = 1;
  lang = "";
  onend: (() => void) | null = null;
  onerror: (() => void) | null = null;
  constructor(public text: string) {}
}

class FakeAudio {
  private listeners: Record<string, () => void> = {};
  constructor(public src: string) {}
  addEventListener(type: string, fn: () => void) {
    this.listeners[type] = fn;
  }
  play() {
    played.push(this.src);
    return Promise.resolve();
  }
  pause() {}
  end() {
    this.listeners.ended?.();
  }
}

function stubFetch(cartesia: boolean, ttsStatus = 200) {
  const fn = vi.fn((url: string, _init?: RequestInit) => {
    void _init;
    if (url.endsWith("/api/health")) {
      return Promise.resolve(new Response(JSON.stringify({ features: { cartesia } }), { status: 200 }));
    }
    if (url.endsWith("/api/tts")) {
      return Promise.resolve(new Response(new Blob(["mp3"], { type: "audio/mpeg" }), { status: ttsStatus }));
    }
    return Promise.resolve(new Response("{}", { status: 404 }));
  });
  vi.stubGlobal("fetch", fn);
  return fn;
}

beforeEach(() => {
  spoken.length = 0;
  played.length = 0;
  vi.stubGlobal("SpeechSynthesisUtterance", FakeUtterance);
  vi.stubGlobal("speechSynthesis", {
    cancel: vi.fn(),
    speak: (u: FakeUtterance) => {
      spoken.push(u.text);
      setTimeout(() => u.onend?.(), 0);
    },
  });
  vi.stubGlobal("Audio", FakeAudio);
  URL.createObjectURL = vi.fn(() => "blob:tts-audio");
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("speak()", () => {
  it("uses Cartesia through the backend when it is configured", async () => {
    const fetchMock = stubFetch(true);
    const { speak } = await freshVoice();
    const handle = await speak("Where is the restroom?");
    expect(handle.engine).toBe("cartesia");
    expect(played).toEqual(["blob:tts-audio"]);
    expect(spoken).toEqual([]);
    const ttsCall = fetchMock.mock.calls.find(([url]) => String(url).endsWith("/api/tts"));
    expect(JSON.parse(ttsCall?.[1]?.body as string)).toEqual({ text: "Where is the restroom?", speed: 1 });
  });

  it("replays the same text from cache without another request", async () => {
    const fetchMock = stubFetch(true);
    const { speak } = await freshVoice();
    await speak("Replay");
    await speak("Replay");
    expect(fetchMock.mock.calls.filter(([url]) => String(url).endsWith("/api/tts"))).toHaveLength(1);
    expect(played).toHaveLength(2);
  });

  it("falls back to the browser voice when Cartesia is not configured", async () => {
    const fetchMock = stubFetch(false);
    const { speak } = await freshVoice();
    const handle = await speak("Hello");
    expect(handle.engine).toBe("browser");
    expect(spoken).toEqual(["Hello"]);
    expect(fetchMock.mock.calls.some(([url]) => String(url).endsWith("/api/tts"))).toBe(false);
  });

  it("falls back to the browser voice when Cartesia fails", async () => {
    stubFetch(true, 503);
    const { speak } = await freshVoice();
    const handle = await speak("Still talking");
    expect(handle.engine).toBe("browser");
    expect(spoken).toEqual(["Still talking"]);
  });
});

describe("ReadAloud", () => {
  it("reads the text, says which voice is used, and can stop", async () => {
    stubFetch(false);
    const cancel = vi.fn();
    // A voice that keeps talking until cancelled, so the in-progress state can be checked.
    vi.stubGlobal("speechSynthesis", { cancel, speak: (u: FakeUtterance) => spoken.push(u.text) });
    vi.resetModules();
    const { default: ReadAloud } = await import("../components/ReadAloud");
    render(<ReadAloud getText={() => "The plan is 16 meters wide."} />);
    await userEvent.click(screen.getByRole("button", { name: "Read aloud" }));
    expect(await screen.findByText("Reading with the browser voice.")).toBeInTheDocument();
    expect(spoken).toEqual(["The plan is 16 meters wide."]);
    const stop = screen.getByRole("button", { name: "Stop reading" });
    expect(stop).toHaveAttribute("aria-pressed", "true");
    await userEvent.click(stop);
    expect(cancel).toHaveBeenCalled();
    expect(await screen.findByText("Stopped.")).toBeInTheDocument();
  });
});
