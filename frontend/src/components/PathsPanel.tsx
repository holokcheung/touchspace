import { useId, useMemo, useState } from "react";
import type { FloorMap } from "../api/types";
import { addPath, describeEdge, pathPoints, removePath } from "../lib/paths";
import { Notice } from "./Status";

/**
 * Record which places a person can walk between. Directions use only these paths, so a
 * new scan has no routes until someone who knows the space adds them here.
 */
export default function PathsPanel({
  map,
  update,
  onStatus,
}: {
  map: FloorMap;
  update: (fn: (m: FloorMap) => FloorMap) => void;
  onStatus: (message: string) => void;
}) {
  const id = useId();
  const points = useMemo(() => pathPoints(map), [map]);
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [hasSteps, setHasSteps] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function add() {
    const a = points.find((p) => p.key === from);
    const b = points.find((p) => p.key === to);
    if (!a || !b) {
      setError("Choose where the path starts and ends.");
      return;
    }
    const result = addPath(map, a, b, hasSteps);
    if (!result.ok) {
      setError(result.error);
      return;
    }
    setError(null);
    update(() => result.map);
    // Continue from where this path ended, which makes chaining a route through doorways quick.
    // The end point is now a graph node, so it has a new key.
    setFrom(`node:${result.edge.b}`);
    setTo("");
    onStatus(`Added a path from ${a.label} to ${b.label}. Save to keep it.`);
  }

  const edges = map.navigation.edges;
  return (
    <section aria-labelledby={`${id}-title`} className="card p-4">
      <h2 id={`${id}-title`} className="text-lg font-bold">
        Walkable paths ({edges.length})
      </h2>
      <p className="text-sm text-muted">
        Directions only use paths recorded here. Connect two points only if someone can walk straight between them, and go
        through doorways rather than walls.
      </p>
      {edges.length === 0 && (
        <div className="mt-3">
          <Notice tone="warning">This map has no paths yet, so the voice explorer can't give directions.</Notice>
        </div>
      )}
      <div className="mt-3 grid gap-2">
        <div>
          <label htmlFor={`${id}-from`} className="field-label">
            From
          </label>
          <select id={`${id}-from`} className="field-input" value={from} onChange={(e) => setFrom(e.target.value)}>
            <option value="">Choose a place or doorway</option>
            {points.map((p) => (
              <option key={p.key} value={p.key}>
                {p.label}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label htmlFor={`${id}-to`} className="field-label">
            To
          </label>
          <select id={`${id}-to`} className="field-input" value={to} onChange={(e) => setTo(e.target.value)}>
            <option value="">Choose a place or doorway</option>
            {points.map((p) => (
              <option key={p.key} value={p.key}>
                {p.label}
              </option>
            ))}
          </select>
        </div>
        <label className="flex min-h-11 items-center gap-2">
          <input type="checkbox" className="h-5 w-5 accent-[var(--accent)]" checked={hasSteps} onChange={(e) => setHasSteps(e.target.checked)} />
          This path has steps
        </label>
        <button type="button" className="btn-secondary" onClick={add}>
          Add path
        </button>
        {error && (
          <p role="alert" className="rounded-md border-l-4 border-danger bg-danger-soft p-2 text-sm">
            <span className="font-bold">Not added: </span>
            {error}
          </p>
        )}
      </div>
      {edges.length > 0 && (
        <details className="mt-3">
          <summary className="cursor-pointer font-semibold">Show all paths</summary>
          <ul className="mt-2 space-y-1 text-sm">
            {edges.map((e) => {
              const { label, length } = describeEdge(map, e);
              return (
                <li key={e.id} className="flex items-center justify-between gap-2">
                  <span>
                    {label} <span className="text-muted">({length.toFixed(1)} m{e.accessibility === "has_steps" ? ", has steps" : ""})</span>
                  </span>
                  <button
                    type="button"
                    className="rounded px-2 py-1 font-semibold text-danger underline"
                    onClick={() => {
                      update((m) => removePath(m, e.id));
                      onStatus(`Removed the path ${label}. Save to keep the change.`);
                    }}
                  >
                    Remove<span className="sr-only"> path {label}</span>
                  </button>
                </li>
              );
            })}
          </ul>
        </details>
      )}
    </section>
  );
}
