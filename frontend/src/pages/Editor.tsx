import { useEffect, useId, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "../api/client";
import { LANDMARK_TYPES, type FloorMap, type Landmark, type Point2D, type ValidationIssue } from "../api/types";
import FloorPlanSvg, { type PlanLayers } from "../components/FloorPlanSvg";
import { SYMBOL_NAMES } from "../components/LandmarkGlyph";
import MapNav from "../components/MapNav";
import PlanDescription from "../components/PlanDescription";
import { LiveStatus, Notice } from "../components/Status";
import { fmt, nearestNode, planBounds, roomAt } from "../lib/geometry";
import { useMapData } from "../lib/useMapData";

const TYPE_LABELS: Record<string, string> = {
  entrance: "Entrance",
  exit: "Exit",
  restroom: "Restroom",
  stairs: "Stairs",
  elevator: "Elevator",
  information: "Information desk",
  room: "Room (no symbol)",
  hallway: "Hallway (no symbol)",
  other: "Other (no symbol)",
};

export default function Editor() {
  const { mapId } = useParams();
  const navigate = useNavigate();
  const { data, error } = useMapData(mapId);
  const [draft, setDraft] = useState<FloorMap | null>(null);
  const [dirty, setDirty] = useState(false);
  const [issues, setIssues] = useState<ValidationIssue[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [layers, setLayers] = useState<PlanLayers>({ rooms: true, objects: true, paths: true, landmarks: true });
  const [status, setStatus] = useState("");
  const [busy, setBusy] = useState<null | "save" | "generate">(null);
  const [actionError, setActionError] = useState<string | null>(null);

  useEffect(() => {
    if (data) {
      setDraft(data.map);
      setIssues(data.issues);
      setDirty(false);
    }
  }, [data]);

  useEffect(() => {
    if (!dirty) return;
    const warn = (e: BeforeUnloadEvent) => e.preventDefault();
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);

  const update = (fn: (m: FloorMap) => FloorMap) => {
    setDraft((m) => (m ? fn(m) : m));
    setDirty(true);
  };
  const updateLandmark = (id: string, patch: Partial<Landmark>) =>
    update((m) => ({ ...m, landmarks: m.landmarks.map((l) => (l.id === id ? { ...l, ...patch } : l)) }));

  const moveLandmark = (id: string, position: Point2D) => {
    updateLandmark(id, { position });
    if (draft) {
      const lm = draft.landmarks.find((l) => l.id === id);
      const room = roomAt(draft, position);
      setStatus(`${lm?.name ?? "Landmark"} moved to ${fmt(position.x)}, ${fmt(position.y)} m${room ? `, in ${room.name}` : ""}.`);
    }
  };

  const addLandmark = () => {
    if (!draft) return;
    const b = planBounds(draft);
    const position = { x: Math.round((b.min_x + b.max_x) * 5) / 10, y: Math.round((b.min_y + b.max_y) * 5) / 10 };
    const id = `lm_${Math.random().toString(36).slice(2, 8)}`;
    const node = nearestNode(draft, position);
    update((m) => ({
      ...m,
      landmarks: [
        ...m.landmarks,
        { id, name: "New landmark", type: "other", position, description: "", show_on_tactile: true, nav_node_id: node?.id ?? null, source: "manual" },
      ],
    }));
    setSelectedId(id);
    setStatus("Added a landmark in the middle of the plan. Rename it and move it with the arrow keys or by dragging.");
  };

  const deleteLandmark = (id: string) => {
    const name = draft?.landmarks.find((l) => l.id === id)?.name;
    update((m) => ({
      ...m,
      landmarks: m.landmarks.filter((l) => l.id !== id),
      start_landmark_id: m.start_landmark_id === id ? null : m.start_landmark_id,
      navigation: { ...m.navigation, nodes: m.navigation.nodes.map((n) => (n.landmark_id === id ? { ...n, landmark_id: null } : n)) },
    }));
    setSelectedId(null);
    setStatus(`Deleted ${name}.`);
  };

  async function save(): Promise<FloorMap | null> {
    if (!draft) return null;
    setBusy("save");
    setActionError(null);
    setStatus("Saving…");
    try {
      const res = await api.saveMap(draft);
      setDraft(res.map);
      setIssues(res.issues);
      setDirty(false);
      const errs = res.issues.filter((i) => i.severity === "error").length;
      const warns = res.issues.filter((i) => i.severity === "warning").length;
      setStatus(`Saved. ${errs} error(s), ${warns} warning(s).`);
      return res.map;
    } catch (e) {
      setActionError(e instanceof Error ? e.message : String(e));
      setStatus("Save failed.");
      return null;
    } finally {
      setBusy(null);
    }
  }

  async function generate() {
    const saved = dirty ? await save() : draft;
    if (!saved) return;
    setBusy("generate");
    setActionError(null);
    setStatus("Generating the 3D tactile model…");
    try {
      await api.generate(saved.id);
      navigate(`/maps/${saved.id}/preview`);
    } catch (e) {
      setActionError(e instanceof Error ? e.message : String(e));
      setStatus("Generation failed.");
      setBusy(null);
    }
  }

  const selected = useMemo(() => draft?.landmarks.find((l) => l.id === selectedId) ?? null, [draft, selectedId]);

  if (error)
    return (
      <div className="mx-auto max-w-3xl px-4 py-12">
        <Notice tone="error" title="Could not load this map">
          {error}
        </Notice>
        <Link to="/upload" className="btn-secondary mt-4">
          Back to uploads
        </Link>
      </div>
    );
  if (!draft) return <p className="p-8 text-muted" role="status">Loading map…</p>;

  const errors = issues.filter((i) => i.severity === "error");
  const warnings = issues.filter((i) => i.severity === "warning");

  return (
    <div>
      <MapNav map={draft} />
      <div className="mx-auto max-w-7xl px-4 py-6">
        <div className="flex flex-wrap items-center gap-3">
          <button type="button" className="btn-secondary" onClick={save} disabled={!dirty || busy !== null}>
            {busy === "save" ? "Saving…" : dirty ? "Save changes" : "All changes saved"}
          </button>
          <button type="button" className="btn-primary" onClick={generate} disabled={busy !== null}>
            {busy === "generate" ? "Generating…" : "Generate 3D tactile map"}
          </button>
          <LiveStatus message={status} />
        </div>
        {actionError && (
          <div className="mt-3">
            <Notice tone="error">{actionError}</Notice>
          </div>
        )}

        <div className="mt-6 grid gap-6 lg:grid-cols-[minmax(0,1fr)_380px]">
          <section aria-labelledby="plan-title" className="min-w-0">
            <h2 id="plan-title" className="sr-only">
              Floor plan
            </h2>
            <fieldset className="mb-3 flex flex-wrap gap-x-5 gap-y-2">
              <legend className="sr-only">Show on the plan</legend>
              {(
                [
                  ["rooms", "Rooms"],
                  ["objects", "Objects"],
                  ["paths", "Walkable paths"],
                  ["landmarks", "Landmarks"],
                ] as const
              ).map(([k, label]) => (
                <label key={k} className="flex min-h-11 items-center gap-2">
                  <input
                    type="checkbox"
                    className="h-5 w-5 accent-[var(--accent)]"
                    checked={layers[k]}
                    onChange={(e) => setLayers((l) => ({ ...l, [k]: e.target.checked }))}
                  />
                  {label}
                </label>
              ))}
            </fieldset>
            <div className="card overflow-hidden p-2">
              <FloorPlanSvg
                map={draft}
                layers={layers}
                selectedId={selectedId}
                onSelect={setSelectedId}
                onMoveLandmark={moveLandmark}
                label="Floor plan. Landmarks are buttons: press Enter to select one and arrow keys to move it (Shift for larger steps)."
              />
            </div>
            <PlanLegend />
            <details className="card mt-4 p-4" open>
              <summary className="cursor-pointer font-bold">Text description of the plan</summary>
              <div className="mt-3">
                <PlanDescription map={draft} />
              </div>
            </details>
          </section>

          <div className="space-y-6">
            <section aria-labelledby="landmarks-title" className="card p-4">
              <div className="flex items-center justify-between gap-2">
                <h2 id="landmarks-title" className="text-lg font-bold">
                  Landmarks
                </h2>
                <button type="button" className="btn-secondary min-h-10 px-3 text-sm" onClick={addLandmark}>
                  Add landmark
                </button>
              </div>
              <ul className="mt-3 space-y-1">
                {draft.landmarks.map((l) => (
                  <li key={l.id}>
                    <button
                      type="button"
                      aria-pressed={l.id === selectedId}
                      onClick={() => setSelectedId(l.id === selectedId ? null : l.id)}
                      className={`flex min-h-11 w-full items-center justify-between rounded-lg px-3 text-left ${l.id === selectedId ? "bg-accent-soft font-bold" : "hover:bg-surface-2"}`}
                    >
                      <span>
                        {l.id === draft.start_landmark_id && <span aria-label="Starting point">★ </span>}
                        {l.name}
                      </span>
                      <span className="text-sm text-muted">{TYPE_LABELS[l.type]}</span>
                    </button>
                  </li>
                ))}
              </ul>
              {selected && (
                <LandmarkForm
                  key={selected.id}
                  map={draft}
                  lm={selected}
                  onChange={(patch) => updateLandmark(selected.id, patch)}
                  onMove={(p) => moveLandmark(selected.id, p)}
                  onSetStart={() => {
                    update((m) => ({ ...m, start_landmark_id: selected.id }));
                    setStatus(`${selected.name} is now the starting point.`);
                  }}
                  onDelete={() => deleteLandmark(selected.id)}
                />
              )}
            </section>

            <section aria-labelledby="rooms-title" className="card p-4">
              <h2 id="rooms-title" className="text-lg font-bold">
                Room names
              </h2>
              <p className="text-sm text-muted">Scanners do not know room names. Name them here.</p>
              <div className="mt-3 space-y-2">
                {draft.rooms.map((r) => (
                  <label key={r.id} className="block">
                    <span className="sr-only">Name for room {r.id}</span>
                    <input
                      className="field-input"
                      value={r.name}
                      onChange={(e) =>
                        update((m) => ({ ...m, rooms: m.rooms.map((x) => (x.id === r.id ? { ...x, name: e.target.value } : x)) }))
                      }
                    />
                  </label>
                ))}
                {draft.rooms.length === 0 && <p className="text-sm text-muted">No rooms were detected.</p>}
              </div>
            </section>

            <ObjectsPanel map={draft} update={update} />

            <section aria-labelledby="check-title" className="card p-4">
              <h2 id="check-title" className="text-lg font-bold">
                Map check
              </h2>
              {dirty && <p className="mt-1 text-sm text-muted">Save to re-check your changes.</p>}
              {errors.length === 0 && warnings.length === 0 ? (
                <p className="mt-2 font-semibold text-ok">No problems found.</p>
              ) : (
                <ul className="mt-2 space-y-2 text-sm">
                  {[...errors, ...warnings].map((i, n) => (
                    <li key={n} className={`rounded-md border-l-4 p-2 ${i.severity === "error" ? "border-danger bg-danger-soft" : "border-warn bg-warn-soft"}`}>
                      <span className="font-bold">{i.severity === "error" ? "Error: " : "Warning: "}</span>
                      {i.message}
                    </li>
                  ))}
                </ul>
              )}
            </section>
          </div>
        </div>
      </div>
    </div>
  );
}

function LandmarkForm({
  map,
  lm,
  onChange,
  onMove,
  onSetStart,
  onDelete,
}: {
  map: FloorMap;
  lm: Landmark;
  onChange: (patch: Partial<Landmark>) => void;
  onMove: (p: Point2D) => void;
  onSetStart: () => void;
  onDelete: () => void;
}) {
  const id = useId();
  const symbol = SYMBOL_NAMES[lm.type];
  return (
    <div className="mt-4 space-y-3 border-t border-line pt-4">
      <h3 className="font-bold">Edit “{lm.name}”</h3>
      <div>
        <label htmlFor={`${id}-name`} className="field-label">
          Name
        </label>
        <input id={`${id}-name`} className="field-input" value={lm.name} maxLength={120} onChange={(e) => onChange({ name: e.target.value })} />
      </div>
      <div>
        <label htmlFor={`${id}-type`} className="field-label">
          Type
        </label>
        <select id={`${id}-type`} className="field-input" value={lm.type} onChange={(e) => onChange({ type: e.target.value as Landmark["type"] })}>
          {LANDMARK_TYPES.map((t) => (
            <option key={t} value={t}>
              {TYPE_LABELS[t]}
            </option>
          ))}
        </select>
        <p className="mt-1 text-sm text-muted">{symbol ? `Printed as a ${symbol}.` : "No tactile symbol; described by voice only."}</p>
      </div>
      <div>
        <label htmlFor={`${id}-desc`} className="field-label">
          Description (optional)
        </label>
        <textarea id={`${id}-desc`} className="field-input" rows={2} value={lm.description} onChange={(e) => onChange({ description: e.target.value })} />
      </div>
      <fieldset className="grid grid-cols-2 gap-2">
        <legend className="field-label">Position in meters</legend>
        {(["x", "y"] as const).map((axis) => (
          <label key={axis} className="text-sm">
            {axis === "x" ? "East (x)" : "North (y)"}
            <input
              type="number"
              step={0.1}
              className="field-input"
              value={lm.position[axis]}
              onChange={(e) => {
                const v = parseFloat(e.target.value);
                if (!Number.isNaN(v)) onMove({ ...lm.position, [axis]: v });
              }}
            />
          </label>
        ))}
      </fieldset>
      <div>
        <label htmlFor={`${id}-node`} className="field-label">
          Linked walkable location
        </label>
        <select id={`${id}-node`} className="field-input" value={lm.nav_node_id ?? ""} onChange={(e) => onChange({ nav_node_id: e.target.value || null })}>
          <option value="">None (routes cannot reach this landmark)</option>
          {map.navigation.nodes.map((n) => (
            <option key={n.id} value={n.id}>
              {n.label ?? n.id}
            </option>
          ))}
        </select>
      </div>
      <label className="flex min-h-11 items-center gap-2">
        <input type="checkbox" className="h-5 w-5 accent-[var(--accent)]" checked={lm.show_on_tactile} onChange={(e) => onChange({ show_on_tactile: e.target.checked })} />
        Print on the tactile map
      </label>
      <div className="flex flex-wrap gap-2">
        <button type="button" className="btn-secondary" onClick={onSetStart} disabled={map.start_landmark_id === lm.id}>
          {map.start_landmark_id === lm.id ? "Starting point" : "Set as starting point"}
        </button>
        <button type="button" className="btn-danger" onClick={onDelete}>
          Delete landmark
        </button>
      </div>
    </div>
  );
}

function ObjectsPanel({ map, update }: { map: FloorMap; update: (fn: (m: FloorMap) => FloorMap) => void }) {
  const set = (id: string, patch: { include_in_tactile?: boolean; hidden?: boolean }) =>
    update((m) => ({ ...m, objects: m.objects.map((o) => (o.id === id ? { ...o, ...patch } : o)) }));
  return (
    <section aria-labelledby="objects-title" className="card p-4">
      <h2 id="objects-title" className="text-lg font-bold">
        Detected objects ({map.objects.length})
      </h2>
      <p className="text-sm text-muted">Furniture is left off the print unless you choose it. Scanner categories can be wrong.</p>
      {map.objects.length === 0 ? (
        <p className="mt-2 text-sm text-muted">No objects.</p>
      ) : (
        <table className="mt-3 w-full text-sm">
          <thead>
            <tr className="text-left text-muted">
              <th scope="col" className="py-1 font-semibold">Object</th>
              <th scope="col" className="py-1 text-center font-semibold">Print</th>
              <th scope="col" className="py-1 text-center font-semibold">Hide</th>
            </tr>
          </thead>
          <tbody>
            {map.objects.map((o) => {
              const name = o.label ?? o.category;
              return (
                <tr key={o.id} className="border-t border-line">
                  <th scope="row" className="py-1 text-left font-normal">
                    {name}
                    {o.label && <span className="text-muted"> ({o.category})</span>}
                  </th>
                  <td className="text-center">
                    <input
                      type="checkbox"
                      aria-label={`Print ${name} on the tactile map`}
                      className="h-5 w-5 accent-[var(--accent)]"
                      checked={o.include_in_tactile}
                      onChange={(e) => set(o.id, { include_in_tactile: e.target.checked })}
                    />
                  </td>
                  <td className="text-center">
                    <input
                      type="checkbox"
                      aria-label={`Hide ${name} from the plan`}
                      className="h-5 w-5 accent-[var(--accent)]"
                      checked={o.hidden}
                      onChange={(e) => set(o.id, { hidden: e.target.checked, include_in_tactile: e.target.checked ? false : o.include_in_tactile })}
                    />
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
    </section>
  );
}

function PlanLegend() {
  return (
    <ul className="mt-3 flex flex-wrap gap-x-5 gap-y-1 text-sm text-muted" aria-label="Plan legend">
      <li>Thick black lines: walls</li>
      <li>Dashed line across a gap: door</li>
      <li>Plain gap: open passage</li>
      <li>Filled gray box: object printed; dashed outline: not printed</li>
      <li>Blue dots: walkable paths</li>
      <li>★ starting point</li>
    </ul>
  );
}
