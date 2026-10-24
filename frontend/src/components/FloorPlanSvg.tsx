import { useRef, type KeyboardEvent, type PointerEvent } from "react";
import type { FloorMap, Landmark, Point2D } from "../api/types";
import { gapEnds, planBounds, polygonCentroid, wallPieces } from "../lib/geometry";
import { LandmarkGlyph } from "./LandmarkGlyph";

export interface PlanLayers {
  rooms: boolean;
  objects: boolean;
  paths: boolean;
  landmarks: boolean;
}

interface Props {
  map: FloorMap;
  layers: PlanLayers;
  selectedId: string | null;
  onSelect?: (id: string | null) => void;
  onMoveLandmark?: (id: string, pos: Point2D) => void;
  label: string;
  /** Route to draw on top of the plan (plan coordinates, start to end). */
  route?: Point2D[];
  /** Places to emphasize (landmark ids), e.g. the ones an answer talks about. */
  highlightIds?: string[];
  /** The walk-through's walker: position, compass heading (0 = north), and what each zone senses. */
  walker?: { position: Point2D; heading: number; hits: Point2D[] };
}

// Plan y points up; SVG y points down. Every plan point is drawn at (x, -y).
const sx = (p: Point2D) => p.x;
const sy = (p: Point2D) => -p.y;

export default function FloorPlanSvg({ map, layers, selectedId, onSelect, onMoveLandmark, label, route, highlightIds = [], walker }: Props) {
  const svgRef = useRef<SVGSVGElement>(null);
  const dragging = useRef<string | null>(null);
  const b = planBounds(map);
  const w = b.max_x - b.min_x;
  const d = b.max_y - b.min_y;
  const pad = Math.max(w, d) * 0.06;
  const unit = Math.max(w, d) / 40; // base size for glyphs/labels, scales with the plan
  const editable = Boolean(onMoveLandmark);

  const toPlan = (clientX: number, clientY: number): Point2D | null => {
    const svg = svgRef.current;
    const ctm = svg?.getScreenCTM();
    if (!svg || !ctm) return null;
    const pt = new DOMPoint(clientX, clientY).matrixTransform(ctm.inverse());
    const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v));
    return { x: clamp(pt.x, b.min_x - pad / 2, b.max_x + pad / 2), y: clamp(-pt.y, b.min_y - pad / 2, b.max_y + pad / 2) };
  };

  const onPointerDown = (e: PointerEvent, lm: Landmark) => {
    onSelect?.(lm.id);
    if (!editable) return;
    dragging.current = lm.id;
    (e.target as Element).setPointerCapture?.(e.pointerId);
  };
  const onPointerMove = (e: PointerEvent) => {
    if (!dragging.current) return;
    const p = toPlan(e.clientX, e.clientY);
    if (p) onMoveLandmark?.(dragging.current, { x: Math.round(p.x * 20) / 20, y: Math.round(p.y * 20) / 20 });
  };
  const endDrag = () => {
    dragging.current = null;
  };

  const onKey = (e: KeyboardEvent, lm: Landmark) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      onSelect?.(lm.id);
      return;
    }
    const step = e.shiftKey ? 0.5 : 0.1;
    const delta: Record<string, [number, number]> = {
      ArrowLeft: [-step, 0],
      ArrowRight: [step, 0],
      ArrowUp: [0, step],
      ArrowDown: [0, -step],
    };
    if (editable && delta[e.key]) {
      e.preventDefault();
      const [dx, dy] = delta[e.key];
      onSelect?.(lm.id);
      onMoveLandmark?.(lm.id, { x: Math.round((lm.position.x + dx) * 100) / 100, y: Math.round((lm.position.y + dy) * 100) / 100 });
    }
  };

  const wallsById = new Map(map.walls.map((wl) => [wl.id, wl]));
  const gaps = [...map.doors, ...map.openings];
  const nodes = new Map(map.navigation.nodes.map((n) => [n.id, n]));

  return (
    <svg
      ref={svgRef}
      viewBox={`${b.min_x - pad} ${-b.max_y - pad} ${w + 2 * pad} ${d + 2 * pad}`}
      className="h-auto w-full touch-none select-none"
      role="group"
      aria-label={label}
      onPointerMove={onPointerMove}
      onPointerUp={endDrag}
      onPointerCancel={endDrag}
      onPointerDown={(e) => {
        if (e.target === svgRef.current) onSelect?.(null);
      }}
    >
      {layers.rooms &&
        map.rooms.map((r) => (
          <polygon key={r.id} points={r.polygon.map((p) => `${sx(p)},${sy(p)}`).join(" ")} fill="var(--plan-room)" />
        ))}

      {layers.objects &&
        map.objects
          .filter((o) => !o.hidden)
          .map((o) => (
            <rect
              key={o.id}
              x={-o.width / 2}
              y={-o.depth / 2}
              width={o.width}
              height={o.depth}
              transform={`translate(${sx(o.position)} ${sy(o.position)}) rotate(${(-o.rotation * 180) / Math.PI})`}
              fill={o.include_in_tactile ? "var(--plan-object)" : "none"}
              stroke="var(--plan-object)"
              strokeWidth={unit * 0.08}
              strokeDasharray={o.include_in_tactile ? undefined : `${unit * 0.25} ${unit * 0.15}`}
            >
              <title>{`${o.label ?? o.category}${o.include_in_tactile ? " (printed)" : " (not printed)"}`}</title>
            </rect>
          ))}

      {map.walls.map((wl) => {
        const own = gaps.filter((g) => g.wall_id === wl.id);
        return wallPieces(wl, own).map(([p, q], i) => (
          <line
            key={`${wl.id}-${i}`}
            x1={sx(p)}
            y1={sy(p)}
            x2={sx(q)}
            y2={sy(q)}
            stroke="var(--plan-wall)"
            strokeWidth={Math.max(wl.thickness, unit * 0.18)}
            strokeLinecap="square"
          />
        ));
      })}

      {map.doors.map((g) => {
        const wl = g.wall_id ? wallsById.get(g.wall_id) : undefined;
        if (!wl) return null;
        const [p, q] = gapEnds(wl, g);
        return (
          <line
            key={g.id}
            x1={sx(p)}
            y1={sy(p)}
            x2={sx(q)}
            y2={sy(q)}
            stroke="var(--accent)"
            strokeWidth={unit * 0.08}
            strokeDasharray={`${unit * 0.18} ${unit * 0.12}`}
          >
            <title>Door</title>
          </line>
        );
      })}

      {layers.paths && (
        <g stroke="var(--plan-path)" strokeWidth={unit * 0.07} strokeDasharray={`${unit * 0.12} ${unit * 0.18}`}>
          {map.navigation.edges.map((e) => {
            const a = nodes.get(e.a);
            const c = nodes.get(e.b);
            if (!a || !c) return null;
            return <line key={e.id} x1={sx(a.position)} y1={sy(a.position)} x2={sx(c.position)} y2={sy(c.position)} />;
          })}
          {map.navigation.nodes.map((n) => (
            <circle key={n.id} cx={sx(n.position)} cy={sy(n.position)} r={unit * 0.12} fill="var(--plan-path)" stroke="none" />
          ))}
        </g>
      )}

      {route && route.length > 1 && (
        <g aria-hidden="true">
          <polyline
            points={route.map((p) => `${sx(p)},${sy(p)}`).join(" ")}
            fill="none"
            stroke="var(--focus)"
            strokeWidth={unit * 0.28}
            strokeLinecap="round"
            strokeLinejoin="round"
            strokeDasharray={`${unit * 0.6} ${unit * 0.25}`}
          />
          <circle cx={sx(route[0])} cy={sy(route[0])} r={unit * 0.35} fill="var(--focus)" />
          <circle
            cx={sx(route[route.length - 1])}
            cy={sy(route[route.length - 1])}
            r={unit * 0.45}
            fill="none"
            stroke="var(--focus)"
            strokeWidth={unit * 0.18}
          />
        </g>
      )}

      {layers.rooms &&
        map.rooms.map((r) => {
          // A landmark with the same name already labels this room.
          if (layers.landmarks && map.landmarks.some((l) => l.name.trim().toLowerCase() === r.name.trim().toLowerCase())) return null;
          const c = polygonCentroid(r.polygon);
          return (
            <text
              key={`label-${r.id}`}
              x={sx(c)}
              y={sy(c) + unit * 1.1}
              fontSize={unit * 0.55}
              textAnchor="middle"
              fill="var(--muted)"
              fontStyle="italic"
              aria-hidden="true"
            >
              {r.name}
            </text>
          );
        })}

      {layers.landmarks &&
        map.landmarks.map((lm) => {
          const selected = lm.id === selectedId;
          const isStart = lm.id === map.start_landmark_id;
          return (
            <g
              key={lm.id}
              transform={`translate(${sx(lm.position)} ${sy(lm.position)})`}
              role="button"
              tabIndex={0}
              aria-pressed={selected}
              aria-label={`${lm.name}, ${lm.type}${isStart ? ", starting point" : ""}${editable ? ". Arrow keys move it." : ""}`}
              className={editable ? "cursor-grab" : "cursor-pointer"}
              onPointerDown={(e) => onPointerDown(e, lm)}
              onKeyDown={(e) => onKey(e, lm)}
            >
              <circle
                r={unit * 0.75}
                fill="var(--surface)"
                stroke={selected || highlightIds.includes(lm.id) ? "var(--focus)" : "transparent"}
                strokeWidth={unit * (highlightIds.includes(lm.id) ? 0.22 : 0.15)}
              />
              <LandmarkGlyph type={lm.type} size={unit * 0.9} color={lm.show_on_tactile ? "var(--plan-landmark)" : "var(--muted)"} />
              <text
                y={-unit * 1.0}
                fontSize={unit * 0.6}
                fontWeight={700}
                textAnchor="middle"
                fill="var(--text)"
                stroke="var(--surface)"
                strokeWidth={unit * 0.18}
                paintOrder="stroke"
              >
                {isStart ? "★ " : ""}
                {lm.name}
              </text>
            </g>
          );
        })}

      {walker && (
        <g aria-hidden="true">
          {walker.hits.map((h, i) => (
            <line
              key={i}
              x1={sx(walker.position)}
              y1={sy(walker.position)}
              x2={sx(h)}
              y2={sy(h)}
              stroke="var(--focus)"
              strokeWidth={unit * 0.06}
              strokeDasharray={`${unit * 0.15} ${unit * 0.1}`}
            />
          ))}
          {walker.hits.map((h, i) => (
            <circle key={`h${i}`} cx={sx(h)} cy={sy(h)} r={unit * 0.15} fill="var(--focus)" />
          ))}
          <g transform={`translate(${sx(walker.position)} ${sy(walker.position)}) rotate(${walker.heading})`}>
            <circle r={unit * 0.55} fill="var(--surface)" stroke="var(--focus)" strokeWidth={unit * 0.12} />
            <polygon points={`0,${-unit * 0.95} ${unit * 0.4},${unit * 0.1} ${-unit * 0.4},${unit * 0.1}`} fill="var(--focus)" />
          </g>
        </g>
      )}
    </svg>
  );
}
