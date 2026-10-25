import { useEffect, useRef, useState } from "react";
import {
  speak,
  stopSpeaking,
  type SpeechHandle,
  type VoiceEngine,
} from "../lib/voice";

const ENGINE_LABEL: Record<VoiceEngine, string> = {
  cartesia: "Cartesia voice",
  browser: "browser voice",
  none: "no voice available",
};

/**
 * Read a block of text aloud, with stop. Meant for low-vision users who don't run a
 * screen reader; screen reader users can keep using their own reader on the same text.
 */
export default function ReadAloud({
  getText,
  label = "Read aloud",
}: {
  getText: () => string;
  label?: string;
}) {
  const [speaking, setSpeaking] = useState(false);
  const [status, setStatus] = useState("");
  const handle = useRef<SpeechHandle | null>(null);

  useEffect(() => () => handle.current?.stop(), []);

  async function toggle() {
    if (speaking) {
      handle.current = null;
      stopSpeaking();
      setSpeaking(false);
      setStatus("Stopped.");
      return;
    }
    setSpeaking(true);
    setStatus("Preparing speech…");
    const h = await speak(getText());
    handle.current = h;
    if (h.engine === "none") {
      setSpeaking(false);
      setStatus("Speech is not available in this browser.");
      return;
    }
    setStatus(`Reading with the ${ENGINE_LABEL[h.engine]}.`);
    await h.done;
    if (handle.current === h) {
      setSpeaking(false);
      setStatus("");
    }
  }

  return (
    <div className="flex flex-wrap items-center gap-3">
      <button
        type="button"
        className="btn-secondary min-h-10 px-3 text-sm"
        aria-pressed={speaking}
        onClick={toggle}
      >
        {speaking ? "Stop reading" : label}
      </button>
      <span role="status" aria-live="polite" className="text-sm text-muted">
        {status}
      </span>
    </div>
  );
}
