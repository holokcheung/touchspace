import { useEffect, useId, useRef, useState, type DragEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { ApiError, api } from "../api/client";
import type { MapResponse, MapSummary } from "../api/types";
import { LiveStatus, Notice } from "../components/Status";

type State =
  | { kind: "idle" }
  | { kind: "uploading"; name: string }
  | { kind: "done"; res: MapResponse }
  | { kind: "error"; message: string; details: string[] };

export default function Upload() {
  const navigate = useNavigate();
  const inputId = useId();
  const inputRef = useRef<HTMLInputElement>(null);
  const [state, setState] = useState<State>({ kind: "idle" });
  const [dragging, setDragging] = useState(false);
  const [maps, setMaps] = useState<MapSummary[] | null>(null);

  useEffect(() => {
    api.listMaps().then(setMaps).catch(() => setMaps([]));
  }, [state.kind]);

  async function send(file: File) {
    if (!file.name.toLowerCase().endsWith(".json") && file.type !== "application/json") {
      setState({ kind: "error", message: `"${file.name}" is not a JSON file. Export the scan as JSON first.`, details: [] });
      return;
    }
    setState({ kind: "uploading", name: file.name });
    try {
      setState({ kind: "done", res: await api.uploadScan(file) });
    } catch (e) {
      const err = e instanceof ApiError ? e : new ApiError(String(e), 0, "unknown");
      setState({ kind: "error", message: err.message, details: err.details });
    } finally {
      if (inputRef.current) inputRef.current.value = "";
    }
  }

  async function loadDemo() {
    setState({ kind: "uploading", name: "the synthetic demo building" });
    try {
      setState({ kind: "done", res: await api.createDemo() });
    } catch (e) {
      setState({ kind: "error", message: e instanceof Error ? e.message : String(e), details: [] });
    }
  }

  function onDrop(e: DragEvent) {
    e.preventDefault();
    setDragging(false);
    const file = e.dataTransfer.files?.[0];
    if (file) send(file);
  }

  const status =
    state.kind === "uploading"
      ? `Uploading and processing ${state.name}…`
      : state.kind === "done"
        ? `Processed ${state.res.map.name}.`
        : state.kind === "error"
          ? "Upload failed."
          : "";

  return (
    <div className="mx-auto max-w-4xl px-4 py-10">
      <h1 className="text-3xl font-bold">Upload a scan</h1>
      <p className="mt-2 text-muted">
        Upload the JSON file exported by the TouchSpace iOS scanner (Apple RoomPlan) or a TouchSpace map file.
        Files stay on this server.
      </p>

      <div
        className={`mt-6 rounded-xl border-2 border-dashed p-8 text-center ${dragging ? "border-accent bg-accent-soft" : "border-line bg-surface"}`}
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
      >
        <p className="text-lg font-bold">Drag and drop a .json scan here</p>
        <p className="mt-1 text-muted">or</p>
        <label htmlFor={inputId} className="btn-primary mt-3 cursor-pointer">
          Choose a file
        </label>
        <input
          id={inputId}
          ref={inputRef}
          type="file"
          accept=".json,application/json"
          className="sr-only"
          onChange={(e) => e.target.files?.[0] && send(e.target.files[0])}
          disabled={state.kind === "uploading"}
        />
        <div className="mt-6 border-t border-line pt-6">
          <p className="text-muted">No scan yet?</p>
          <button type="button" className="btn-secondary mt-2" onClick={loadDemo} disabled={state.kind === "uploading"}>
            Load the demo scan (synthetic)
          </button>
        </div>
      </div>

      <div className="mt-4">
        <LiveStatus message={status} />
      </div>

      {state.kind === "error" && (
        <Notice tone="error" title="We could not use that file">
          <p>{state.message}</p>
          {state.details.length > 0 && (
            <ul className="mt-2 list-disc pl-6 text-sm">
              {state.details.map((d) => (
                <li key={d}>{d}</li>
              ))}
            </ul>
          )}
        </Notice>
      )}

      {state.kind === "done" && <UploadResult res={state.res} onContinue={() => navigate(`/maps/${state.res.map.id}/edit`)} />}

      <section aria-labelledby="maps-title" className="mt-12">
        <h2 id="maps-title" className="text-xl font-bold">
          Your maps
        </h2>
        {maps === null ? (
          <p className="mt-2 text-muted">Loading…</p>
        ) : maps.length === 0 ? (
          <p className="mt-2 text-muted">No maps yet.</p>
        ) : (
          <ul className="mt-3 divide-y divide-line rounded-xl border border-line bg-surface">
            {maps.map((m) => (
              <li key={m.id} className="flex flex-wrap items-center justify-between gap-3 p-4">
                <div>
                  <p className="font-bold">{m.name}</p>
                  <p className="text-sm text-muted">
                    {m.synthetic ? "Synthetic demo · " : ""}
                    {m.walls} walls · {m.landmarks} landmarks · 3D model:{" "}
                    {m.model_status === "ready" ? "up to date" : m.model_status === "stale" ? "out of date" : "not generated"}
                  </p>
                </div>
                <div className="flex gap-2">
                  <Link to={`/maps/${m.id}/edit`} className="btn-secondary">
                    Edit<span className="sr-only"> {m.name}</span>
                  </Link>
                  <Link to={`/maps/${m.id}/preview`} className="btn-secondary">
                    3D preview<span className="sr-only"> of {m.name}</span>
                  </Link>
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}

function UploadResult({ res, onContinue }: { res: MapResponse; onContinue: () => void }) {
  const m = res.map;
  const errors = res.issues.filter((i) => i.severity === "error");
  const warnings = res.issues.filter((i) => i.severity === "warning");
  return (
    <div className="card mt-2 p-6">
      <h2 className="text-xl font-bold">{m.name}</h2>
      {m.source.kind === "synthetic" && <p className="mt-1 text-sm text-muted">Synthetic layout, not a real scan.</p>}
      <dl className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
        {[
          ["Walls", m.walls.length],
          ["Doors and openings", m.doors.length + m.openings.length],
          ["Objects", m.objects.length],
          ["Landmarks", m.landmarks.length],
        ].map(([k, v]) => (
          <div key={k as string} className="rounded-lg bg-surface-2 p-3">
            <dt className="text-sm text-muted">{k}</dt>
            <dd className="text-2xl font-bold">{v}</dd>
          </div>
        ))}
      </dl>
      {m.bounds && (
        <p className="mt-3 text-muted">
          Footprint: {(m.bounds.max_x - m.bounds.min_x).toFixed(1)} m by {(m.bounds.max_y - m.bounds.min_y).toFixed(1)} m.
        </p>
      )}
      {res.processing_steps.length > 0 && (
        <>
          <h3 className="mt-4 font-bold">Clean-up applied</h3>
          <ul className="mt-1 list-disc pl-6 text-muted">
            {res.processing_steps.map((s) => (
              <li key={s}>{s}</li>
            ))}
          </ul>
        </>
      )}
      {(errors.length > 0 || warnings.length > 0) && (
        <div className="mt-4">
          <Notice tone={errors.length ? "error" : "warning"} title={`${errors.length} error(s), ${warnings.length} warning(s)`}>
            <ul className="list-disc pl-6 text-sm">
              {[...errors, ...warnings].map((i, n) => (
                <li key={n}>{i.message}</li>
              ))}
            </ul>
            <p className="mt-2 text-sm">You can fix these in the floor-plan editor.</p>
          </Notice>
        </div>
      )}
      <button type="button" className="btn-primary mt-6" onClick={onContinue}>
        Continue to the floor-plan editor
      </button>
    </div>
  );
}
