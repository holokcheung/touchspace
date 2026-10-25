import {
  Component,
  lazy,
  Suspense,
  useCallback,
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { Link, useParams } from "react-router-dom";
import type { FloorMap } from "../api/types";
import FloorPlanSvg from "../components/FloorPlanSvg";
import Icon, { type IconName } from "../components/Icon";
import PlanDescription from "../components/PlanDescription";
import ReadAloud from "../components/ReadAloud";
import { Notice } from "../components/Status";
import {
  DotPadPanel, ZOOM_LEVELS, framePins, mapPins, statusLine, type ZoomAction,
} from "../dotpad";
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
  readZones,
  turn,
  type Pose,
  type Scene,
} from "../lib/soundscape";
import { SoundscapeAudio } from "../lib/soundscapeAudio";
import { useMapData } from "../lib/useMapData";
import { useWalkthroughAssistant } from "../lib/useWalkthroughAssistant";
import { speak, stopSpeaking } from "../lib/voice";
const WalkthroughScene = lazy(() => import("../components/WalkthroughScene"));
class SceneBoundary extends Component<
  { children: ReactNode },
  { failed: boolean }
> {
  state = { failed: false };
  static getDerivedStateFromError() {
    return { failed: true };
  }
  render() {
    return this.state.failed ? (
      <p className="scene-fallback">
        3D is unavailable. Continue with the floor plan, keyboard and audio
        guidance.
      </p>
    ) : (
      this.props.children
    );
  }
}
type Action =
  | "forward"
  | "back"
  | "left"
  | "right"
  | "big-left"
  | "big-right"
  | "around"
  | "describe";

const LAYERS = { rooms: true, objects: true, paths: false, landmarks: true };
const W = SOUNDSCAPE.walk;

function startPose(map: FloorMap, landmarkId: string | null): Pose {
  const lm = map.landmarks.find((l) => l.id === landmarkId);
  if (lm) return { position: { ...lm.position }, heading: 0 };
  const b = planBounds(map);
  return {
    position: { x: (b.min_x + b.max_x) / 2, y: (b.min_y + b.max_y) / 2 },
    heading: 0,
  };
}

function nearbyLandmarks(scene: Scene, pose: Pose): Set<string> {
  return new Set(
    scene.map.landmarks
      .filter((l) => dist(l.position, pose.position) <= W.nearby_landmark_m)
      .map((l) => l.id),
  );
}

const cap = (s: string) => s[0].toUpperCase() + s.slice(1);

/** A button that acts once per press, and repeats while held (touch or mouse). */
function HoldButton({
  onAct,
  className,
  children,
  label,
}: {
  onAct: () => void;
  className?: string;
  children: ReactNode;
  label?: string;
}) {
  const act = useRef(onAct);
  act.current = onAct;
  const timer = useRef<number | null>(null);
  const repeated = useRef(false);
  const stop = () => {
    if (timer.current !== null) window.clearTimeout(timer.current);
    timer.current = null;
  };
  useEffect(() => {
    const hidden = () => {
      if (document.hidden) stop();
    };
    window.addEventListener("blur", stop);
    document.addEventListener("visibilitychange", hidden);
    return () => {
      stop();
      window.removeEventListener("blur", stop);
      document.removeEventListener("visibilitychange", hidden);
    };
  }, []);
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

export function WalkthroughView({
  map,
  header,
  online = false,
}: {
  map: FloorMap;
  header?: ReactNode;
  online?: boolean;
}) {
  const ids = useId();
  const scene = useMemo(() => buildScene(map), [map]);

  const [pose, setPose] = useState<Pose | null>(null);
  const [startId, setStartId] = useState("");
  const [soundOn, setSoundOn] = useState(false);
  const [soundError, setSoundError] = useState<string | null>(null);
  const [volume, setVolume] = useState(SOUNDSCAPE.noise.default_volume);
  const [speakOn, setSpeakOn] = useState(true);
  const [status, setStatus] = useState("");
  const [panel, setPanel] = useState<
    "map" | "audio" | "dotpad" | "help" | null
  >(() => (window.innerWidth >= 1000 ? "map" : null));
  const [typed, setTyped] = useState("");
  const [showText, setShowText] = useState(false);
  const [avoidStairs, setAvoidStairs] = useState(false);
  const [dotZoomIndex, setDotZoomIndex] = useState(0);
  const dotZoom = ZOOM_LEVELS[dotZoomIndex];
  const zoomDotPad = useCallback((action: ZoomAction) => {
    setDotZoomIndex((index) =>
      Math.max(0, Math.min(ZOOM_LEVELS.length - 1, index + (action === "in" ? 1 : -1))),
    );
  }, []);
  const assistant = useWalkthroughAssistant(
    map,
    pose,
    speakOn,
    online,
    avoidStairs,
  );
  const busyRef = useRef(false);
  busyRef.current = assistant.busy;
  const spaceHeld = useRef(false);
  const drag = useRef<{ x: number; heading: number } | null>(null);

  const audio = useRef<SoundscapeAudio | null>(null);
  const walkRef = useRef<HTMLDivElement>(null);
  const descriptionRef = useRef<HTMLDivElement>(null);
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
    if (map && scene && !poseRef.current)
      placeAt(map.start_landmark_id ?? map.landmarks[0]?.id ?? "");
  }, [map, scene, placeAt]);

  useEffect(
    () => () => {
      void audio.current?.stop();
      stopSpeaking();
    },
    [],
  );

  const readings = useMemo(
    () => (scene && pose ? readZones(scene, pose) : []),
    [scene, pose],
  );
  const dataHere = scene && pose ? hasMapData(scene, pose.position) : true;
  const dotCenter = dotZoom > 1 ? pose?.position : undefined;
  const dot = useMemo(
    () => mapPins(map, undefined, undefined, { zoom: dotZoom, center: dotCenter }),
    [map, dotZoom, dotCenter],
  );
  const route = assistant.activeRoute;
  const routePoints = route?.points;
  const frame = useMemo(
    () => framePins(dot.grid, dot.layout, pose, dot.placed, routePoints),
    [dot, pose, routePoints],
  );
  const padText = useMemo(() => statusLine(map, pose), [map, pose]);

  useEffect(() => {
    if (!soundOn || readings.length === 0) return;
    const by = Object.fromEntries(readings.map((r) => [r.zone, r.distance]));
    audio.current?.update({
      left: by.left ?? null,
      ahead: by.ahead ?? null,
      right: by.right ?? null,
      hasData: dataHere,
    });
  }, [readings, dataHere, soundOn]);

  const announce = useCallback((text: string, aloud = true) => {
    setStatus(text);
    if (aloud && speakRef.current) void speak(text);
  }, []);

  const act = useCallback(
    (action: Action) => {
      const p = poseRef.current;
      if (!scene || !p || busyRef.current) return;
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
          announce(
            `${cap(r.blockedBy ?? "something")} ${action === "forward" ? "ahead" : "behind you"}.`,
            now - lastBump.current > 2500,
          );
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
          parts.push(
            roomAfter && roomAfter !== roomBefore
              ? `Through the ${gapName(g)}, into ${roomAfter.name}.`
              : `Through the ${gapName(g)}.`,
          );
        } else if (roomAfter && roomBefore && roomAfter !== roomBefore) {
          parts.push(`Now in ${roomAfter.name}.`);
        }
        if (hadData && !hasData)
          parts.push(
            "Leaving the mapped area. There's no map information here.",
          );
        if (!hadData && hasData)
          parts.push(
            `Back on the map${roomAfter ? `, in ${roomAfter.name}` : ""}.`,
          );
        const nowNear = nearbyLandmarks(scene, next);
        for (const l of scene.map.landmarks) {
          if (nowNear.has(l.id) && !near.current.has(l.id)) {
            parts.push(
              `${l.name}, ${meters(dist(l.position, next.position))} ${directionTo(next, l.position)}.`,
            );
          }
        }
        near.current = nowNear;
        poseRef.current = next;
        setPose(next);
        if (parts.length) announce(parts.join(" "));
        return;
      }
      const deg = {
        left: -W.turn_deg,
        right: W.turn_deg,
        "big-left": -W.big_turn_deg,
        "big-right": W.big_turn_deg,
        around: 180,
      }[action];
      const next = turn(p, deg);
      poseRef.current = next;
      setPose(next);
      // Speak the compass direction only when it changes, so small turns stay quiet.
      if (
        compassName(next.heading) !== compassName(p.heading) ||
        Math.abs(deg) >= 90
      )
        announce(`Facing ${compassName(next.heading)}.`);
    },
    [scene, announce],
  );

  useEffect(() => {
    const isInput = (target: EventTarget | null) =>
      target instanceof Element &&
      Boolean(
        target.closest(
          "input, textarea, select, button, a, summary, [contenteditable='true']",
        ),
      );
    const down = (e: globalThis.KeyboardEvent) => {
      if (e.altKey || e.ctrlKey || e.metaKey || isInput(e.target)) return;
      if (e.code === "Space" || e.key === " ") {
        e.preventDefault();
        if (!e.repeat && !spaceHeld.current) {
          spaceHeld.current = true;
          void assistant.press();
        }
        return;
      }
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
        enter: "describe",
        e: "describe",
      };
      const action = keys[e.key.toLowerCase()];
      if (action) {
        e.preventDefault();
        act(action);
      }
    };
    const up = (e: globalThis.KeyboardEvent) => {
      if ((e.code === "Space" || e.key === " ") && spaceHeld.current) {
        spaceHeld.current = false;
        e.preventDefault();
        assistant.release();
      }
    };
    const blur = () => {
      spaceHeld.current = false;
      drag.current = null;
    };
    window.addEventListener("keydown", down);
    window.addEventListener("keyup", up);
    window.addEventListener("blur", blur);
    return () => {
      window.removeEventListener("keydown", down);
      window.removeEventListener("keyup", up);
      window.removeEventListener("blur", blur);
    };
  }, [act, assistant.press, assistant.release]);

  useEffect(() => {
    audio.current?.setVolume(
      assistant.phase !== "idle" ? volume * 0.18 : volume,
    );
  }, [assistant.phase, volume, soundOn]);

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
      audio.current = engine;
      await engine.start(volume);
      audio.current = engine;
      setSoundOn(true);
      announce("Sound on. Walk with the arrow keys or the buttons.", false);
      walkRef.current?.focus();
    } catch (e) {
      void engine.stop();
      audio.current = null;
      setSoundError(e instanceof Error ? e.message : String(e));
    }
  }

  if (!pose)
    return (
      <p className="p-8 text-muted" role="status">
        Loading map…
      </p>
    );
  const room = roomAt(map, pose.position);
  const location = dataHere
    ? (room?.name ?? "On the map")
    : "Outside the mapped area";
  const hits = readings.flatMap((r) => (r.hit ? [r.hit] : []));
  const tabs: {
    id: NonNullable<typeof panel>;
    name: string;
    icon: IconName;
  }[] = [
    { id: "map", name: "Floor plan", icon: "map" },
    { id: "audio", name: "Audio", icon: "audio" },
    { id: "dotpad", name: "DotPad", icon: "dotpad" },
    { id: "help", name: "Controls", icon: "help" },
  ];
  const phaseText = {
    idle: "Hold Space to ask anything about this space",
    starting: "Opening microphone…",
    listening: "Listening · release to send",
    thinking: "Thinking…",
    speaking: "Speaking · hold Space to ask another question",
  }[assistant.phase];

  return (
    <div
      className="walkthrough-shell"
      ref={walkRef}
      tabIndex={0}
      role="application"
      aria-roledescription="walk area"
      aria-label="Walk area"
      aria-describedby={`${ids}-keys`}
    >
      <div
        className="walk-scene"
        onPointerDown={(e) => {
          if (assistant.busy) return;
          walkRef.current?.focus();
          e.currentTarget.setPointerCapture(e.pointerId);
          drag.current = { x: e.clientX, heading: poseRef.current!.heading };
        }}
        onPointerMove={(e) => {
          if (!drag.current || assistant.busy) return;
          const next = turn(
            poseRef.current!,
            drag.current.heading +
              (e.clientX - drag.current.x) * 0.25 -
              poseRef.current!.heading,
          );
          poseRef.current = next;
          setPose(next);
        }}
        onPointerUp={() => {
          drag.current = null;
        }}
        onPointerCancel={() => {
          drag.current = null;
        }}
        aria-hidden="true"
      >
        <SceneBoundary>
          <Suspense
            fallback={<p className="scene-fallback">Building your space…</p>}
          >
            <WalkthroughScene map={map} pose={pose} route={routePoints} />
          </Suspense>
        </SceneBoundary>
      </div>
      <div className="walk-vignette" aria-hidden="true" />
      <header className="walk-header">
        {header ?? (
          <a
            className="walk-icon-button"
            href="/"
            aria-label="Leave walkthrough"
          >
            <Icon name="back" />
          </a>
        )}
        <div className="walk-title">
          <span className="eyebrow">
            TOUCHSPACE /{" "}
            {map.source.kind === "synthetic" ? "DEMO SPACE" : "WALKTHROUGH"}
          </span>
          <h1>{map.name.replace(/\s*\(Synthetic\)/i, "")}</h1>
        </div>
        <div className="walk-heading">
          <span
            className="compass-arrow"
            style={{ transform: `rotate(${-pose.heading}deg)` }}
          >
            ↑
          </span>
          <span>
            {compassName(pose.heading)}
            <small>{Math.round(pose.heading)}°</small>
          </span>
        </div>
      </header>
      <nav className="walk-tools" aria-label="Walkthrough panels">
        {tabs.map((t) => (
          <button
            key={t.id}
            className={`walk-tool ${panel === t.id ? "active" : ""}`}
            aria-label={t.name}
            aria-expanded={panel === t.id}
            aria-controls={`${ids}-${t.id}`}
            onClick={() => setPanel(panel === t.id ? null : t.id)}
          >
            <Icon name={t.icon} />
            <span>{t.name}</span>
          </button>
        ))}
      </nav>
      {tabs.map((t) => (
        <aside
          key={t.id}
          id={`${ids}-${t.id}`}
          className="walk-panel"
          hidden={panel !== t.id}
          aria-label={t.name}
        >
          <div className="panel-heading">
            <div>
              <span className="eyebrow">YOUR SPACE AT A GLANCE</span>
              <h2>{t.name}</h2>
            </div>
            <button
              className="panel-close"
              aria-label={`Close ${t.name}`}
              onClick={() => {
                setPanel(null);
                walkRef.current?.focus();
              }}
            >
              <Icon name="close" />
            </button>
          </div>
          {t.id === "map" && (
            <div className="space-y-4">
              <div className="plan-caption">
                <span>
                  <i /> You are here
                </span>
                <span>↑ North up</span>
              </div>
              <FloorPlanSvg
                map={map}
                layers={LAYERS}
                selectedId={null}
                label="Global floor plan"
                walker={{ ...pose, hits }}
                route={routePoints}
                highlightIds={assistant.result?.place_ids}
              />
              <div className="location-card">
                <span className="eyebrow">CURRENT POSITION</span>
                <strong>{location}</strong>
                <span>
                  Facing {compassName(pose.heading)} ·{" "}
                  {pose.position.x.toFixed(1)}, {pose.position.y.toFixed(1)} m
                </span>
              </div>
              <label htmlFor={`${ids}-start`} className="field-label">
                Start from
              </label>
              <select
                id={`${ids}-start`}
                className="field-input"
                value={startId}
                disabled={assistant.busy}
                onChange={(e) => {
                  assistant.stop();
                  placeAt(e.target.value);
                }}
              >
                <option value="">Middle of the map</option>
                {map.landmarks.map((l) => (
                  <option key={l.id} value={l.id}>
                    {l.name}
                  </option>
                ))}
              </select>
              <label className="flex min-h-11 items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={avoidStairs}
                  onChange={(e) => setAvoidStairs(e.target.checked)}
                />
                Prefer routes without stairs
              </label>
              {route?.found && (
                <div className="route-summary">
                  <strong>To {route.destination_name}</strong>
                  <p>
                    {meters(route.distance_m)} · from {route.origin_name}
                  </p>
                  <ol className="mt-2 list-decimal space-y-2 pl-5">
                    {route.steps.map((s, i) => (
                      <li key={i}>{s.instruction}</li>
                    ))}
                  </ol>
                </div>
              )}
              <details>
                <summary className="cursor-pointer text-sm font-semibold">
                  Read the floor plan
                </summary>
                <div className="mt-3">
                  <ReadAloud
                    getText={() => descriptionRef.current?.innerText ?? ""}
                    label="Read the floor plan aloud"
                  />
                  <div ref={descriptionRef} className="mt-3">
                    <PlanDescription map={map} />
                  </div>
                </div>
              </details>
            </div>
          )}
          {t.id === "audio" && (
            <div className="space-y-5">
              <p className="text-sm text-muted">
                Put on headphones. Hear how the space changes as you move.
              </p>
              <button
                className="btn-primary w-full"
                aria-pressed={soundOn}
                onClick={() => void toggleSound()}
              >
                {soundOn ? "Stop sound" : "Start sound"}
              </button>
              <label className="field-label" htmlFor={`${ids}-vol`}>
                Volume: {Math.round(volume * 100)}%
              </label>
              <input
                id={`${ids}-vol`}
                type="range"
                min="0"
                max="1"
                step="0.05"
                value={volume}
                className="w-full"
                onChange={(e) => setVolume(Number(e.target.value))}
              />
              <label className="flex min-h-11 items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={speakOn}
                  onChange={(e) => {
                    setSpeakOn(e.target.checked);
                    if (!e.target.checked) {
                      stopSpeaking();
                      assistant.stop();
                    }
                  }}
                />
                Speak announcements and answers
              </label>
              <dl className="sound-key">
                <dt>Muffled noise, left or right</dt>
                <dd>A wall or furniture is close on that side.</dd>
                <dt>Faster ticks</dt>
                <dd>Something is getting closer ahead.</dd>
                <dt>Doorway chime</dt>
                <dd>You crossed a door or opening.</dd>
                <dt>Low warning tone</dt>
                <dd>You have left the mapped area.</dd>
              </dl>
              {soundError && (
                <p role="alert" className="text-danger">
                  {soundError}
                </p>
              )}
              <h3 className="font-bold">Around you now</h3>
              <dl>
                {readings.map((r) => (
                  <div key={r.zone} className="sensor-reading">
                    <dt>{cap(r.label)}</dt>
                    <dd>
                      {r.distance === null
                        ? "Clear within sensing range"
                        : `${r.what} · ${meters(r.distance)}`}
                    </dd>
                  </div>
                ))}
              </dl>
            </div>
          )}
          {t.id === "dotpad" && (
            <DotPadPanel
              grid={frame.grid}
              walker={frame.walker}
              text={padText}
              metersPerPin={dot.layout.metersPerPin}
              zoom={dotZoom}
              onZoom={zoomDotPad}
              routeName={route?.destination_name}
              onDismissRoute={assistant.dismissRoute}
            />
          )}
          {t.id === "help" && (
            <div className="space-y-5 text-sm">
              <p id={`${ids}-keys`}>
                Arrow keys or W/S move and A/D turn. Hold Shift for a quarter
                turn. Drag the view to look around. T turns around. E or Enter
                describes your surroundings.
              </p>
              <p>
                <kbd>Space</kbd> Hold to talk, release to send. You can also
                hold the microphone button, or choose “Type a question”.
                Keyboard and screen reader users can press Enter on the
                microphone to start and stop.
              </p>
              <p>
                Steps are {Math.round(W.step_m * 100)} cm. Movement pauses while
                you ask a question.
              </p>
              <p>
                This is simulated from the map, not live sensing. People, moved
                furniture and unrecorded obstacles are not detected.
              </p>
              <p>
                {map.source.kind === "synthetic"
                  ? "This demo layout is synthetic."
                  : map.source.description}
              </p>
            </div>
          )}
        </aside>
      ))}
      <div className="walk-position">
        <span className="position-dot" />
        <span>
          {location} · facing {compassName(pose.heading)}
        </span>
        <span className="practice-tag">Virtual practice</span>
      </div>
      <div className="walk-step-controls" aria-label="Movement controls">
        <HoldButton
          className="step-button turn-left"
          onAct={() => act("left")}
          label="Turn left"
        >
          ↶
        </HoldButton>
        <HoldButton
          className="step-button forward"
          onAct={() => act("forward")}
          label="Step forward"
        >
          <Icon name="arrow" />
        </HoldButton>
        <HoldButton
          className="step-button turn-right"
          onAct={() => act("right")}
          label="Turn right"
        >
          ↷
        </HoldButton>
        <HoldButton
          className="step-button backward"
          onAct={() => act("back")}
          label="Step backward"
        >
          <Icon name="arrow" className="rotate-180" />
        </HoldButton>
      </div>
      <div className="walk-assistant">
        {(assistant.answer || assistant.question || assistant.error) && (
          <div className="assistant-answer" aria-live="polite">
            {assistant.question && (
              <p className="asked-question">You · {assistant.question}</p>
            )}
            {assistant.answer && <p>{assistant.answer}</p>}
            {assistant.error && <p role="alert">{assistant.error}</p>}
          </div>
        )}
        <p className="walk-status" role="status" aria-label="Navigation">
          {status || "Take a look around. Your guide is here when you need it."}
        </p>
        {showText && (
          <form
            className="assistant-text-form"
            onSubmit={(e) => {
              e.preventDefault();
              if (!assistant.busy) {
                void assistant.ask(typed);
                setTyped("");
              }
            }}
          >
            <input
              autoFocus
              aria-label="Your question"
              placeholder="Where is the restroom?"
              value={typed}
              maxLength={1000}
              onChange={(e) => setTyped(e.target.value)}
            />
            <button
              aria-label="Send question"
              disabled={assistant.busy || !typed.trim()}
            >
              <Icon name="send" />
            </button>
          </form>
        )}
        <div
          className={`voice-bar ${assistant.phase === "listening" ? "listening" : ""}`}
        >
          <button
            className="talk-button"
            aria-label="Hold to ask TouchSpace"
            aria-pressed={assistant.phase === "listening"}
            disabled={assistant.phase === "thinking"}
            onPointerDown={(e) => {
              e.preventDefault();
              e.currentTarget.setPointerCapture?.(e.pointerId);
              void assistant.press();
            }}
            onPointerUp={() => assistant.release()}
            onPointerCancel={() => assistant.release()}
            onLostPointerCapture={() => assistant.release()}
            onKeyDown={(e) => {
              if (e.key === " " && !e.repeat) {
                e.preventDefault();
                void assistant.press();
              }
            }}
            onKeyUp={(e) => {
              if (e.key === " ") {
                e.preventDefault();
                assistant.release();
              }
            }}
            onClick={(e) => {
              if (e.detail === 0) {
                if (assistant.phase === "listening") assistant.release();
                else void assistant.press();
              }
            }}
          >
            <Icon name="mic" />
          </button>
          <div className="voice-prompt">
            <strong aria-live="polite">{phaseText}</strong>
            <span>Try “Where is the exit?” or “What’s around me?”</span>
          </div>
          <button
            className="type-question"
            aria-expanded={showText}
            onClick={() => setShowText(!showText)}
          >
            {showText ? "Close typing" : "Type a question"}
          </button>
          {assistant.phase === "speaking" && (
            <button className="type-question" onClick={assistant.stop}>
              Stop
            </button>
          )}
        </div>
        <div className="walk-bottom-hints">
          <span>
            <kbd>↑</kbd>
            <kbd>↓</kbd> move <kbd>←</kbd>
            <kbd>→</kbd> turn · drag to look
          </span>
          <button onClick={() => act("describe")}>What's around me?</button>
        </div>
      </div>
      <p className="sr-only">
        Simulated from the map, not live sensing. Use headphones for directional
        audio.
      </p>
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
        <Link to="/" className="btn-secondary mt-4">
          Back to spaces
        </Link>
      </div>
    );
  if (!data)
    return (
      <p className="p-8 text-muted" role="status">
        Loading map…
      </p>
    );
  return (
    <WalkthroughView
      key={data.map.id}
      map={data.map}
      online
      header={
        <Link
          className="walk-icon-button"
          to="/"
          aria-label="Leave walkthrough"
        >
          <Icon name="back" />
        </Link>
      }
    />
  );
}
