import { useCallback, useEffect, useId, useMemo, useRef, useState, type FormEvent } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api/client";
import type { AskContext, AskResult } from "../api/types";
import FloorPlanSvg from "../components/FloorPlanSvg";
import MapNav from "../components/MapNav";
import { LiveStatus, Notice } from "../components/Status";
import { playCue } from "../lib/cues";
import { useMapData } from "../lib/useMapData";
import { cartesiaAvailable, createListener, speak, stopSpeaking, type Listener, type VoiceEngine } from "../lib/voice";

interface Turn {
  id: number;
  question: string;
  heard: boolean; // asked by voice
  result: AskResult | null;
  error: string | null;
}

const SUGGESTIONS = [
  "Describe this room.",
  "Where is the main entrance?",
  "Where is the restroom?",
  "How do I get there from the main entrance?",
  "What is near the entrance?",
  "How do I get from the entrance to the exit?",
];

const LAYERS = { rooms: true, objects: false, paths: false, landmarks: true };

export default function VoiceExplorer() {
  const { mapId } = useParams();
  const { data, error } = useMapData(mapId);
  const ids = useId();
  const [question, setQuestion] = useState("");
  const [turns, setTurns] = useState<Turn[]>([]);
  const [busy, setBusy] = useState(false);
  const [context, setContext] = useState<AskContext>({ last_place_id: null, current_place_id: null, avoid_stairs: false });
  const [speakAnswers, setSpeakAnswers] = useState(true);
  const [voiceEngine, setVoiceEngine] = useState<"cartesia" | "browser" | null>(null);
  const [listening, setListening] = useState(false);
  const [listenEngine, setListenEngine] = useState<VoiceEngine | null>(null);
  const [status, setStatus] = useState("");
  const [speakingId, setSpeakingId] = useState<number | null>(null);
  const listener = useRef<Listener | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const nextId = useRef(1);

  const map = data?.map;
  const startOptions = useMemo(() => (map ? map.landmarks.filter((l) => l.nav_node_id) : []), [map]);

  useEffect(() => {
    if (map && context.current_place_id === null && map.start_landmark_id) {
      setContext((c) => ({ ...c, current_place_id: map.start_landmark_id }));
    }
  }, [map, context.current_place_id]);

  useEffect(() => {
    cartesiaAvailable().then((ok) => setVoiceEngine(ok ? "cartesia" : "browser"));
    return () => stopSpeaking();
  }, []);

  const say = useCallback(async (turnId: number, text: string) => {
    setSpeakingId(turnId);
    const h = await speak(text);
    await h.done;
    setSpeakingId((cur) => (cur === turnId ? null : cur));
  }, []);

  const ask = useCallback(
    async (q: string, heard = false) => {
      const text = q.trim();
      if (!text || !mapId || busy) return;
      const id = nextId.current++;
      setTurns((t) => [...t, { id, question: text, heard, result: null, error: null }]);
      setQuestion("");
      setBusy(true);
      setStatus("Thinking…");
      try {
        const result = await api.ask(mapId, text, context);
        setContext(result.context);
        setTurns((t) => t.map((x) => (x.id === id ? { ...x, result } : x)));
        setStatus("");
        if (speakAnswers) {
          const spoken = result.safety_note ? `${result.answer} ${result.safety_note}` : result.answer;
          void say(id, spoken);
        }
      } catch (e) {
        const message = e instanceof Error ? e.message : String(e);
        setTurns((t) => t.map((x) => (x.id === id ? { ...x, error: message } : x)));
        setStatus("The question could not be answered.");
        playCue("error");
      } finally {
        setBusy(false);
        inputRef.current?.focus();
      }
    },
    [mapId, busy, context, speakAnswers, say],
  );

  async function toggleMic() {
    if (listening) {
      playCue("listen-stop");
      setStatus("Transcribing…");
      await listener.current?.stop();
      return;
    }
    stopSpeaking();
    listener.current = await createListener({
      onResult: (text) => {
        setStatus(`Heard: ${text}`);
        void ask(text, true);
      },
      onError: (message) => {
        setListening(false);
        setStatus(message);
        playCue("error");
      },
      onStateChange: setListening,
    });
    setListenEngine(listener.current.engine);
    if (listener.current.engine === "none") {
      await listener.current.start(); // reports that voice input is unavailable
      inputRef.current?.focus();
      return;
    }
    playCue("listen-start");
    setStatus("Listening. Ask your question, then press the button again.");
    await listener.current.start();
  }

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    void ask(question);
  }

  if (error)
    return (
      <div className="mx-auto max-w-3xl px-4 py-12">
        <Notice tone="error" title="Could not load this map">
          {error}
        </Notice>
      </div>
    );
  if (!map) return <p className="p-8 text-muted" role="status">Loading map…</p>;

  const lastWithPlaces = [...turns].reverse().find((t) => t.result && (t.result.route?.found || t.result.place_ids.length));
  const shownRoute = lastWithPlaces?.result?.route?.found ? lastWithPlaces.result.route.points : undefined;
  const highlight = lastWithPlaces?.result?.place_ids ?? [];
  const noPaths = map.navigation.edges.length === 0;

  return (
    <div>
      <MapNav map={map} />
      <div className="mx-auto max-w-7xl px-4 py-6">
        <Notice tone="info" title="A travel aid, not a replacement for your cane or guide dog">
          Answers come only from this map. Directions follow the paths recorded on it and can't detect obstacles or people.
          TouchSpace doesn't track where you are; you choose your starting point.
        </Notice>

        <div className="mt-6 grid gap-6 lg:grid-cols-[minmax(0,1fr)_420px]">
          <section aria-labelledby={`${ids}-chat`} className="min-w-0">
            <h2 id={`${ids}-chat`} className="sr-only">
              Ask TouchSpace
            </h2>

            <form onSubmit={onSubmit} className="card p-4">
              <label htmlFor={`${ids}-q`} className="field-label text-base">
                Ask a question about this map
              </label>
              <div className="flex flex-wrap gap-2">
                <input
                  id={`${ids}-q`}
                  ref={inputRef}
                  className="field-input min-w-0 flex-1"
                  value={question}
                  onChange={(e) => setQuestion(e.target.value)}
                  placeholder="For example: Where is the restroom?"
                  autoComplete="off"
                  autoFocus
                />
                <button type="submit" className="btn-primary" disabled={busy || !question.trim()}>
                  Ask
                </button>
                <button
                  type="button"
                  className={listening ? "btn-danger" : "btn-secondary"}
                  aria-pressed={listening}
                  onClick={toggleMic}
                  disabled={busy && !listening}
                >
                  {listening ? "Stop and ask" : "Speak a question"}
                </button>
              </div>
              <div className="mt-2">
                <LiveStatus message={status} />
              </div>
              <p className="text-sm text-muted">
                Voice: {voiceEngine === "cartesia" ? "Cartesia" : voiceEngine === "browser" ? "browser built-in" : "checking…"}
                {listenEngine && listenEngine !== "none" ? ` · Listening with ${listenEngine === "cartesia" ? "Cartesia" : "browser recognition"}` : ""}
                . A rising tone means the microphone is on; a falling tone means it stopped.
              </p>
            </form>

            <div className="mt-4">
              <h3 className="text-sm font-bold text-muted">Try asking</h3>
              <ul className="mt-2 flex flex-wrap gap-2">
                {SUGGESTIONS.map((s) => (
                  <li key={s}>
                    <button type="button" className="btn-secondary min-h-10 px-3 text-sm" onClick={() => ask(s)} disabled={busy}>
                      {s}
                    </button>
                  </li>
                ))}
              </ul>
            </div>

            {noPaths && (
              <div className="mt-4">
                <Notice tone="warning" title="No walking paths on this map yet">
                  I can describe places, but I can't give directions until paths are recorded. Scans from RoomPlan don't include
                  them.
                </Notice>
              </div>
            )}

            <h3 className="mt-6 text-lg font-bold">Conversation</h3>
            {turns.length === 0 ? (
              <p className="mt-2 text-muted">No questions yet.</p>
            ) : (
              <ol className="mt-3 space-y-4" role="log" aria-live="polite" aria-relevant="additions text">
                {turns.map((t) => (
                  <li key={t.id} className="card p-4">
                    <p>
                      <span className="font-bold">{t.heard ? "You said: " : "You asked: "}</span>
                      {t.question}
                    </p>
                    {t.error && (
                      <p className="mt-2 text-danger" role="alert">
                        Error: {t.error}
                      </p>
                    )}
                    {!t.result && !t.error && <p className="mt-2 text-muted">Thinking…</p>}
                    {t.result && (
                      <div className="mt-2 space-y-2">
                        <p>
                          <span className="font-bold">TouchSpace: </span>
                          {t.result.route?.found
                            ? `Route from ${t.result.route.origin_name} to ${t.result.route.destination_name}, about ${Math.max(1, Math.round(t.result.route.distance_m))} meters along recorded paths:`
                            : t.result.answer}
                        </p>
                        {t.result.route?.found && (
                          <ol className="list-decimal space-y-1 pl-6" aria-label={`Directions to ${t.result.route.destination_name}`}>
                            {t.result.route.steps.map((s, i) => (
                              <li key={i}>{s.instruction}</li>
                            ))}
                          </ol>
                        )}
                        {t.result.safety_note && <p className="text-sm text-muted">{t.result.safety_note}</p>}
                        {t.result.understood_by === "gemini" && (
                          <p className="text-sm text-muted">Gemini helped interpret this question. The answer itself comes from the map.</p>
                        )}
                        <div className="flex flex-wrap gap-2">
                          <button
                            type="button"
                            className="btn-secondary min-h-10 px-3 text-sm"
                            onClick={() => say(t.id, t.result!.safety_note ? `${t.result!.answer} ${t.result!.safety_note}` : t.result!.answer)}
                          >
                            Replay answer
                          </button>
                          {speakingId === t.id && (
                            <button
                              type="button"
                              className="btn-secondary min-h-10 px-3 text-sm"
                              onClick={() => {
                                stopSpeaking();
                                setSpeakingId(null);
                              }}
                            >
                              Stop speaking
                            </button>
                          )}
                          {t.result.suggestions.slice(0, 2).map((s) => (
                            <button key={s} type="button" className="btn-secondary min-h-10 px-3 text-sm" onClick={() => ask(s)} disabled={busy}>
                              {s}
                            </button>
                          ))}
                        </div>
                      </div>
                    )}
                  </li>
                ))}
              </ol>
            )}
          </section>

          <aside aria-labelledby={`${ids}-settings`} className="space-y-6">
            <section className="card p-4">
              <h2 id={`${ids}-settings`} className="text-lg font-bold">
                Settings
              </h2>
              <label htmlFor={`${ids}-start`} className="field-label mt-3">
                I'm starting from
              </label>
              <select
                id={`${ids}-start`}
                className="field-input"
                value={context.current_place_id ?? ""}
                onChange={(e) => setContext((c) => ({ ...c, current_place_id: e.target.value || null }))}
              >
                <option value="">Not set</option>
                {startOptions.map((l) => (
                  <option key={l.id} value={l.id}>
                    {l.name}
                  </option>
                ))}
              </select>
              <label className="mt-3 flex min-h-11 items-center gap-2">
                <input
                  type="checkbox"
                  className="h-5 w-5 accent-[var(--accent)]"
                  checked={context.avoid_stairs}
                  onChange={(e) => setContext((c) => ({ ...c, avoid_stairs: e.target.checked }))}
                />
                Avoid stairs in directions
              </label>
              <label className="flex min-h-11 items-center gap-2">
                <input
                  type="checkbox"
                  className="h-5 w-5 accent-[var(--accent)]"
                  checked={speakAnswers}
                  onChange={(e) => {
                    setSpeakAnswers(e.target.checked);
                    if (!e.target.checked) stopSpeaking();
                  }}
                />
                Speak answers aloud
              </label>
              <p className="text-sm text-muted">Turn this off if your screen reader already reads the answers.</p>
            </section>

            <section aria-labelledby={`${ids}-map`} className="card p-2">
              <h2 id={`${ids}-map`} className="px-2 pt-2 text-lg font-bold">
                Map
              </h2>
              <p className="px-2 text-sm text-muted">The latest route is drawn as an orange dashed line, from the dot to the ring.</p>
              <FloorPlanSvg
                map={map}
                layers={LAYERS}
                selectedId={null}
                route={shownRoute}
                highlightIds={highlight}
                label="Floor plan. The conversation lists the same information as text."
              />
              <p className="px-2 pb-2 text-sm">
                <Link to={`/maps/${map.id}/edit`} className="font-semibold underline">
                  Edit landmarks and paths
                </Link>
              </p>
            </section>
          </aside>
        </div>
      </div>
    </div>
  );
}
