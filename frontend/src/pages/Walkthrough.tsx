import { useCallback, useEffect, useId, useMemo, useRef, useState, type KeyboardEvent, type ReactNode } from "react";
import { useParams } from "react-router-dom";
import type { FloorMap } from "../api/types";
import DotPadPreview from "../components/DotPadPreview";
import FloorPlanSvg from "../components/FloorPlanSvg";
import MapNav from "../components/MapNav";
import { LiveStatus, Notice } from "../components/Status";
import { framePins, mapPins, statusLine } from "../lib/dotpad";
import { dist, planBounds, roomAt } from "../lib/geometry";
import {
  SOUNDSCAPE,
  buildScene,
  compassName,
  describeSurroundings,
  directionTo,
  freeSpotNear,
  gapName,
  hasMapData,
  meters,
  move,
  muffleFor,
  readZones,
  turn,
  type Pose,
  type Reading,
  type Scene,
} from "../lib/soundscape";
import { SoundscapeAudio } from "../lib/soundscapeAudio";
import { useMapData } from "../lib/useMapData";
import { speak, stopSpeaking } from "../lib/voice";

type Action = "forward" | "back" | "left" | "right" | "big-left" | "big-right" | "around" | "describe";

const LAYERS = { rooms: true, objects: true, paths: false, landmarks: true };
const W = SOUNDSCAPE.walk;

function startPose(map: FloorMap, landmarkId: string | null): Pose {
  const lm = map.landmarks.find((l) => l.id === landmarkId);
  if (lm) return { position: { ...lm.position }, heading: 0 };
  const b = planBounds(map);
  return { position: { x: (b.min_x + b.max_x) / 2, y: (b.min_y + b.max_y) / 2 }, heading: 0 };
}

function nearbyLandmarks(scene: Scene, pose: Pose): Set<string> {
  return new Set(scene.map.landmarks.filter((l) => dist(l.position, pose.position) <= W.nearby_landmark_m).map((l) => l.id));
}

const cap = (s: string) => s[0].toUpperCase() + s.slice(1);

/** A button that acts once per press, and repeats while held (touch or mouse). */
function HoldButton({ onAct, className, children, label }: { onAct: () => void; className?: string; children: ReactNode; label?: string }) {
  const act = useRef(onAct);
  act.current = onAct;
  const timer = useRef<number | null>(null);
  const repeated = useRef(false);
  const stop = () => {
    if (timer.current !== null) window.clearTimeout(timer.current);
    timer.current = null;
  };
  useEffect(() => stop, []);
  return (
    <button
      type="button"
      aria-label={label}
      className={className}
      onPointerDown={() => {
        repeated.current = false;
        stop();
        timer.current = window.setTimeout(function repeat() {
          repeated.current = true;
          act.current();
          timer.current = window.setTimeout(repeat, W.hold_repeat_s * 1000);
        }, 380);
      }}
      onPointerUp={stop}
      onPointerLeave={stop}
      onPointerCancel={stop}
      onContextMenu={(e) => e.preventDefault()}
      onClick={() => {
        // The press already acted while held; the click at release shouldn't add another step.
        if (repeated.current) {
          repeated.current = false;
          return;
        }
        act.current();
      }}
    >
      {children}
    </button>
  );
}

function ReadingRow({ r }: { r: Reading }) {
  const m = muffleFor(r.distance);
  return (
    <div className="flex items-baseline justify-between gap-3 border-t border-line py-2 first:border-t-0">
      <dt className="font-bold">{cap(r.label)}</dt>
      <dd className="text-right">
        {r.distance === null ? (
          <span className="text-muted">nothing within {meters(SOUNDSCAPE.sensing.max_range_m)}</span>
        ) : (
          <>
            {r.what} {meters(r.distance)}
            {r.zone !== "ahead" && m.amount > 0 && <span className="text-muted"> · muffled {Math.round(m.amount * 100)}%</span>}
          </>
        )}
      </dd>
    </div>
  );
}

/** The walk-through itself, for any map. The standalone page (standalone/walk.tsx) uses it without the backend. */
export function WalkthroughView({ map, header }: { map: FloorMap; header?: ReactNode }) {
  const ids = useId();
  const scene = useMemo(() => buildScene(map), [map]);

  const [pose, setPose] = useState<Pose | null>(null);
  const [startId, setStartId] = useState("");
  const [soundOn, setSoundOn] = useState(false);
  const [soundError, setSoundError] = useState<string | null>(null);
  const [volume, setVolume] = useState(SOUNDSCAPE.noise.default_volume);
  const [speakOn, setSpeakOn] = useState(true);
  const [status, setStatus] = useState("");

  const audio = useRef<SoundscapeAudio | null>(null);
  const walkRef = useRef<HTMLDivElement>(null);
  const poseRef = useRef<Pose | null>(null);
  const near = useRef<Set<string>>(new Set());
  const lastBump = useRef(0);
  const speakRef = useRef(speakOn);
  speakRef.current = speakOn;

  const placeAt = useCallback(
    (landmarkId: string) => {
      if (!map || !scene) return;
      const start = startPose(map, landmarkId || null);
      const p = { ...start, position: freeSpotNear(scene, start.position) };
      poseRef.current = p;
      near.current = nearbyLandmarks(scene, p);
      setPose(p);
      setStartId(landmarkId);
    },
    [map, scene],
  );

  useEffect(() => {
    if (map && scene && !poseRef.current) placeAt(map.start_landmark_id ?? map.landmarks[0]?.id ?? "");
  }, [map, scene, placeAt]);

  useEffect(
    () => () => {
      void audio.current?.stop();
      stopSpeaking();
    },
    [],
  );

  const readings = useMemo(() => (scene && pose ? readZones(scene, pose) : []), [scene, pose]);
  const dataHere = scene && pose ? hasMapData(scene, pose.position) : true;
  const dot = useMemo(() => mapPins(map), [map]);
  const frame = useMemo(() => framePins(dot.grid, dot.layout, pose, dot.placed), [dot, pose]);
  const padText = useMemo(() => statusLine(map, pose), [map, pose]);

  useEffect(() => {
    if (!soundOn || readings.length === 0) return;
    const by = Object.fromEntries(readings.map((r) => [r.zone, r.distance]));
    audio.current?.update({ left: by.left ?? null, ahead: by.ahead ?? null, right: by.right ?? null, hasData: dataHere });
  }, [readings, dataHere, soundOn]);

  const announce = useCallback((text: string, aloud = true) => {
    setStatus(text);
    if (aloud && speakRef.current) void speak(text);
  }, []);

  const act = useCallback(
    (action: Action) => {
      const p = poseRef.current;
      if (!scene || !p) return;
      if (action === "describe") {
        announce(describeSurroundings(scene, p));
        return;
      }
      if (action === "forward" || action === "back") {
        const r = move(scene, p, action === "forward" ? W.step_m : -W.step_m);
        if (r.blocked) {
          audio.current?.cue("bump");
          const now = Date.now();
          // Holding a button against a wall shouldn't repeat the words, only the bump.
          announce(`${cap(r.blockedBy ?? "something")} ${action === "forward" ? "ahead" : "behind you"}.`, now - lastBump.current > 2500);
          lastBump.current = now;
          return;
        }
        const next = r.pose;
        const parts: string[] = [];
        const roomBefore = roomAt(scene.map, p.position);
        const roomAfter = roomAt(scene.map, next.position);
        const hadData = hasMapData(scene, p.position);
        const hasData = hasMapData(scene, next.position);
        if (r.crossed.length) {
          audio.current?.cue("doorway");
          const g = r.crossed[0];
          parts.push(roomAfter && roomAfter !== roomBefore ? `Through the ${gapName(g)}, into ${roomAfter.name}.` : `Through the ${gapName(g)}.`);
        } else if (roomAfter && roomBefore && roomAfter !== roomBefore) {
          parts.push(`Now in ${roomAfter.name}.`);
        }
        if (hadData && !hasData) parts.push("Leaving the mapped area. There's no map information here.");
        if (!hadData && hasData) parts.push(`Back on the map${roomAfter ? `, in ${roomAfter.name}` : ""}.`);
        const nowNear = nearbyLandmarks(scene, next);
        for (const l of scene.map.landmarks) {
          if (nowNear.has(l.id) && !near.current.has(l.id)) {
            parts.push(`${l.name}, ${meters(dist(l.position, next.position))} ${directionTo(next, l.position)}.`);
          }
        }
        near.current = nowNear;
        poseRef.current = next;
        setPose(next);
        if (parts.length) announce(parts.join(" "));
        return;
      }
      const deg = { left: -W.turn_deg, right: W.turn_deg, "big-left": -W.big_turn_deg, "big-right": W.big_turn_deg, around: 180 }[action];
      const next = turn(p, deg);
      poseRef.current = next;
      setPose(next);
      // Speak the compass direction only when it changes, so small turns stay quiet.
      if (compassName(next.heading) !== compassName(p.heading) || Math.abs(deg) >= 90) announce(`Facing ${compassName(next.heading)}.`);
    },
    [scene, announce],
  );

  function onKeyDown(e: KeyboardEvent) {
    const k = e.key.toLowerCase();
    const keys: Record<string, Action> = {
      arrowup: "forward",
      w: "forward",
      arrowdown: "back",
      s: "back",
      arrowleft: e.shiftKey ? "big-left" : "left",
      a: e.shiftKey ? "big-left" : "left",
      arrowright: e.shiftKey ? "big-right" : "right",
      d: e.shiftKey ? "big-right" : "right",
      t: "around",
      " ": "describe",
      enter: "describe",
    };
    const action = keys[k];
    if (!action) return;
    e.preventDefault();
    act(action);
  }

  async function toggleSound() {
    if (soundOn) {
      await audio.current?.stop();
      audio.current = null;
      setSoundOn(false);
      announce("Sound off.", false);
      return;
    }
    setSoundError(null);
    const engine = new SoundscapeAudio();
    try {
      await engine.start(volume);
      audio.current = engine;
      setSoundOn(true);
      announce("Sound on. Walk with the arrow keys or the buttons.", false);
      walkRef.current?.focus();
    } catch (e) {
      setSoundError(e instanceof Error ? e.message : String(e));
    }
  }

  if (!pose) return <p className="p-8 text-muted" role="status">Loading map…</p>;

  const room = roomAt(map, pose.position);
  const hits = readings.flatMap((r) => (r.hit ? [r.hit] : []));
  const btn = "btn-secondary min-h-16 w-full px-2 text-base";

  return (
    <div>
      {header}
      <div className="mx-auto max-w-7xl px-4 py-6">
        <Notice tone="info" title="Practice walking this map with sound">
          Put on headphones. A soft noise plays in each ear; it gets muffled on the side where a wall or furniture is close, and
          ticks mean something is ahead. This is simulated from the map, not live sensing: it can't know about people, moved
          furniture or anything that isn't on the map.
        </Notice>

        <div className="mt-6 grid gap-6 lg:grid-cols-[minmax(0,1fr)_420px]">
          <div className="min-w-0 space-y-6">
            <section aria-labelledby={`${ids}-sound`} className="card p-4">
              <h2 id={`${ids}-sound`} className="text-lg font-bold">
                Sound
              </h2>
              <div className="mt-3 flex flex-wrap items-end gap-4">
                <button type="button" className={soundOn ? "btn-danger" : "btn-primary"} aria-pressed={soundOn} onClick={toggleSound}>
                  {soundOn ? "Stop sound" : "Start sound"}
                </button>
                <div className="min-w-48 flex-1">
                  <label htmlFor={`${ids}-vol`} className="field-label">
                    Volume: {Math.round(volume * 100)}%
                  </label>
                  <input
                    id={`${ids}-vol`}
                    type="range"
                    min={0}
                    max={1}
                    step={0.05}
                    value={volume}
                    className="h-11 w-full accent-[var(--accent)]"
                    onChange={(e) => {
                      const v = Number(e.target.value);
                      setVolume(v);
                      audio.current?.setVolume(v);
                    }}
                  />
                </div>
              </div>
              {soundError && (
                <p className="mt-2 text-danger" role="alert">
                  {soundError}
                </p>
              )}
              <label className="mt-3 flex min-h-11 items-center gap-2">
                <input
                  type="checkbox"
                  className="h-5 w-5 accent-[var(--accent)]"
                  checked={speakOn}
                  onChange={(e) => {
                    setSpeakOn(e.target.checked);
                    if (!e.target.checked) stopSpeaking();
                  }}
                />
                Speak announcements (doors, rooms, places)
              </label>
              <p className="text-sm text-muted">
                Keep the volume low enough to hear the room around you. On iPhone, the sound plays even with the silent switch on.
              </p>
              <label htmlFor={`${ids}-start`} className="field-label mt-3">
                Start from
              </label>
              <select id={`${ids}-start`} className="field-input" value={startId} onChange={(e) => placeAt(e.target.value)}>
                <option value="">Middle of the map</option>
                {map.landmarks.map((l) => (
                  <option key={l.id} value={l.id}>
                    {l.name}
                  </option>
                ))}
              </select>
            </section>

            <section aria-labelledby={`${ids}-walk`} className="card p-4">
              <h2 id={`${ids}-walk`} className="text-lg font-bold">
                Walk
              </h2>
              <div
                ref={walkRef}
                tabIndex={0}
                role="application"
                aria-roledescription="walk area"
                aria-label="Walk area"
                aria-describedby={`${ids}-keys`}
                onKeyDown={onKeyDown}
                className="mt-3 rounded-lg border-2 border-dashed border-line p-3 focus:border-solid focus:border-[var(--focus)]"
              >
                <p id={`${ids}-keys`} className="text-sm text-muted">
                  Keyboard: click or tab here, then Up and Down arrows walk {Math.round(W.step_m * 100)} centimeters at a time, Left and Right turn{" "}
                  {W.turn_deg}° (with Shift, {W.big_turn_deg}°), T turns around, and Space says what's around you.
                </p>
                <p className="mt-2 text-lg font-bold">
                  {dataHere ? (room ? room.name : "On the map") : "Outside the mapped area"} · facing {compassName(pose.heading)}
                </p>
                {dataHere ? (
                  <dl className="mt-1">
                    {readings.map((r) => (
                      <ReadingRow key={r.zone} r={r} />
                    ))}
                  </dl>
                ) : (
                  <p className="mt-1">No map information here, so the noise is replaced by a repeating two-note cue. Turn around to go back.</p>
                )}
              </div>
              <div className="mt-2">
                <LiveStatus message={status} />
              </div>

              <div className="mt-2 grid grid-cols-3 gap-2" role="group" aria-label="Walk controls">
                <HoldButton className={btn} onAct={() => act("left")} label={`Turn left ${W.turn_deg} degrees`}>
                  ↺ Turn left
                </HoldButton>
                <HoldButton className="btn-primary min-h-16 w-full px-2 text-base" onAct={() => act("forward")} label="Step forward">
                  ↑ Forward
                </HoldButton>
                <HoldButton className={btn} onAct={() => act("right")} label={`Turn right ${W.turn_deg} degrees`}>
                  ↻ Turn right
                </HoldButton>
                <HoldButton className={btn} onAct={() => act("big-left")} label={`Turn left ${W.big_turn_deg} degrees`}>
                  ⟲ Left 90°
                </HoldButton>
                <HoldButton className={btn} onAct={() => act("back")} label="Step back">
                  ↓ Back
                </HoldButton>
                <HoldButton className={btn} onAct={() => act("big-right")} label={`Turn right ${W.big_turn_deg} degrees`}>
                  ⟳ Right 90°
                </HoldButton>
                <button type="button" className={`${btn} col-span-2`} onClick={() => act("describe")}>
                  What's around me?
                </button>
                <button type="button" className={btn} onClick={() => act("around")}>
                  Turn around
                </button>
              </div>
              <p className="mt-2 text-sm text-muted">Hold Forward or Back to keep walking.</p>
            </section>
          </div>

          <aside className="space-y-6">
            <section aria-labelledby={`${ids}-map`} className="card p-2">
              <h2 id={`${ids}-map`} className="px-2 pt-2 text-lg font-bold">
                Map
              </h2>
              <p className="px-2 text-sm text-muted">
                The orange arrow is you. Dashed lines reach the nearest surface on your left, ahead and right.
              </p>
              <FloorPlanSvg
                map={map}
                layers={LAYERS}
                selectedId={null}
                walker={{ position: pose.position, heading: pose.heading, hits }}
                label="Floor plan with your position. The walk area lists the same information as text."
              />
            </section>

            <section aria-labelledby={`${ids}-dotpad`} className="card p-4">
              <h2 id={`${ids}-dotpad`} className="text-lg font-bold">
                DotPad
              </h2>
              <p className="text-sm text-muted">
                What the DotPad's pins will show: walls, doorways as gaps, a symbol for each marked place, and an X for you that
                moves as you walk. The text line under it says the room and which way you face.
              </p>
              <div className="mt-3">
                <DotPadPreview grid={frame.grid} walker={frame.walker} text={padText} metersPerPin={dot.layout.metersPerPin} />
              </div>
            </section>
          </aside>
        </div>
      </div>
    </div>
  );
}

export default function Walkthrough() {
  const { mapId } = useParams();
  const { data, error } = useMapData(mapId);
  if (error)
    return (
      <div className="mx-auto max-w-3xl px-4 py-12">
        <Notice tone="error" title="Could not load this map">
          {error}
        </Notice>
      </div>
    );
  if (!data) return <p className="p-8 text-muted" role="status">Loading map…</p>;
  return <WalkthroughView key={data.map.id} map={data.map} header={<MapNav map={data.map} />} />;
}
