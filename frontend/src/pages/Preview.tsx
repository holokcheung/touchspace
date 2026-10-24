import { useCallback, useEffect, useId, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api/client";
import type { ModelStatus, TactileSettings } from "../api/types";
import MapNav from "../components/MapNav";
import ModelViewer, { type ViewerHandle } from "../components/ModelViewer";
import { LiveStatus, Notice } from "../components/Status";
import { useMapData } from "../lib/useMapData";

type NumKey = {
  [K in keyof TactileSettings]: TactileSettings[K] extends number ? K : never;
}[keyof TactileSettings];
type BoolKey = {
  [K in keyof TactileSettings]: TactileSettings[K] extends boolean ? K : never;
}[keyof TactileSettings];

// Ranges mirror backend/app/models/tactile.py.
const NUMBER_FIELDS: { key: NumKey; label: string; min: number; max: number; step: number }[] = [
  { key: "max_width_mm", label: "Maximum width", min: 40, max: 400, step: 5 },
  { key: "max_depth_mm", label: "Maximum depth", min: 40, max: 400, step: 5 },
  { key: "base_thickness_mm", label: "Base thickness", min: 1, max: 10, step: 0.5 },
  { key: "wall_height_mm", label: "Wall height above base", min: 0.5, max: 10, step: 0.5 },
  { key: "wall_width_mm", label: "Wall width", min: 0.8, max: 8, step: 0.2 },
  { key: "min_door_gap_mm", label: "Minimum door gap", min: 0, max: 30, step: 0.5 },
  { key: "landmark_size_mm", label: "Symbol size", min: 3, max: 20, step: 0.5 },
  { key: "landmark_height_mm", label: "Symbol height", min: 0.5, max: 10, step: 0.5 },
];

const BOOL_FIELDS: { key: BoolKey; label: string }[] = [
  { key: "include_landmarks", label: "Landmark symbols" },
  { key: "include_legend", label: "Symbol legend strip" },
  { key: "include_objects", label: "Selected furniture" },
  { key: "include_paths", label: "Dotted walkable paths" },
  { key: "orientation_marker", label: "Cut corner for orientation" },
];

export default function Preview() {
  const { mapId } = useParams();
  const { data, error } = useMapData(mapId);
  const [model, setModel] = useState<ModelStatus | null>(null);
  const [settings, setSettings] = useState<TactileSettings | null>(null);
  const [busy, setBusy] = useState(false);
  const [genError, setGenError] = useState<{ message: string; details: string[] } | null>(null);
  const [viewerError, setViewerError] = useState<string | null>(null);
  const [status, setStatus] = useState("");
  const viewer = useRef<ViewerHandle>(null);
  const autoStarted = useRef(false);
  const formId = useId();

  const generate = useCallback(
    async (s?: TactileSettings) => {
      if (!mapId) return;
      setBusy(true);
      setGenError(null);
      setStatus("Generating the tactile model…");
      try {
        const m = await api.generate(mapId, s);
        setModel(m);
        setStatus(`Model ready: ${m.report?.width_mm.toFixed(0)} by ${m.report?.depth_mm.toFixed(0)} millimeters.`);
      } catch (e) {
        const details = (e as { details?: string[] }).details ?? [];
        setGenError({ message: e instanceof Error ? e.message : String(e), details });
        setStatus("Generation failed.");
      } finally {
        setBusy(false);
      }
    },
    [mapId],
  );

  useEffect(() => {
    if (!data) return;
    setModel(data.model);
    setSettings(data.map.tactile);
    if (data.model.status === "none" && !autoStarted.current) {
      autoStarted.current = true;
      generate();
    }
  }, [data, generate]);

  const onViewerError = useCallback((m: string) => setViewerError(m), []);

  if (error)
    return (
      <div className="mx-auto max-w-3xl px-4 py-12">
        <Notice tone="error" title="Could not load this map">
          {error}
        </Notice>
      </div>
    );
  if (!data || !settings) return <p className="p-8 text-muted" role="status">Loading map…</p>;

  const report = model?.report ?? null;
  const ready = model && model.status !== "none" && report;
  const stlUrl = api.stlUrl(data.map.id, model?.generated_at);
  const settingsChanged = report && JSON.stringify(settings) !== JSON.stringify(report.settings);

  return (
    <div>
      <MapNav map={data.map} />
      <div className="mx-auto max-w-7xl px-4 py-6">
        <div className="flex flex-wrap items-center gap-3">
          {ready ? (
            <a href={stlUrl} download={model.filename ?? "touchspace-map.stl"} className="btn-primary px-6 text-lg">
              Download STL
              <span className="sr-only">
                {" "}
                ({report.width_mm.toFixed(0)} by {report.depth_mm.toFixed(0)} mm)
              </span>
            </a>
          ) : (
            <button type="button" className="btn-primary px-6 text-lg" disabled>
              Download STL
            </button>
          )}
          <button type="button" className="btn-secondary" onClick={() => generate(settings)} disabled={busy}>
            {busy ? "Generating…" : "Regenerate model"}
          </button>
          {model?.filename && <span className="text-sm text-muted">File: {model.filename}</span>}
          <LiveStatus message={status} />
        </div>

        <div className="mt-3 space-y-3">
          {model?.status === "stale" && (
            <Notice tone="warning" title="This model is out of date">
              The floor plan changed after this model was generated. Regenerate before downloading.
            </Notice>
          )}
          {genError && (
            <Notice tone="error" title="Could not generate the model">
              <p>{genError.message}</p>
              {genError.details.length > 0 && (
                <ul className="mt-1 list-disc pl-6 text-sm">
                  {genError.details.map((d) => (
                    <li key={d}>{d}</li>
                  ))}
                </ul>
              )}
              <Link to={`/maps/${data.map.id}/edit`} className="mt-2 inline-block font-semibold underline">
                Open the floor-plan editor
              </Link>
            </Notice>
          )}
          {viewerError && <Notice tone="error">{viewerError}</Notice>}
        </div>

        <div className="mt-6 grid gap-6 lg:grid-cols-[minmax(0,1fr)_360px]">
          <section aria-labelledby="viewer-title" className="min-w-0">
            <h2 id="viewer-title" className="sr-only">
              3D preview
            </h2>
            {ready ? (
              <ModelViewer
                key={stlUrl}
                ref={viewer}
                url={stlUrl}
                onError={onViewerError}
                label="3D preview of the tactile map. A text description follows below."
              />
            ) : (
              <div className="grid aspect-[4/3] place-items-center rounded-xl border border-line bg-surface-2 text-muted" role="status">
                {busy ? "Generating the tactile model…" : "No model yet."}
              </div>
            )}
            <div className="mt-3 flex flex-wrap gap-2" role="group" aria-label="Camera controls">
              <button type="button" className="btn-secondary" onClick={() => viewer.current?.reset()} disabled={!ready}>
                Reset view
              </button>
              <button type="button" className="btn-secondary" onClick={() => viewer.current?.top()} disabled={!ready}>
                View from above
              </button>
              <button type="button" className="btn-secondary" onClick={() => viewer.current?.zoom(0.8)} disabled={!ready}>
                Zoom in
              </button>
              <button type="button" className="btn-secondary" onClick={() => viewer.current?.zoom(1.25)} disabled={!ready}>
                Zoom out
              </button>
            </div>
            <p className="mt-2 text-sm text-muted">Drag to rotate, scroll or pinch to zoom, right-drag to pan.</p>

            {report && (
              <section aria-labelledby="desc-title" className="card mt-6 p-5">
                <h2 id="desc-title" className="text-lg font-bold">
                  Text description of the tactile map
                </h2>
                <ul className="mt-3 list-disc space-y-1 pl-5">
                  {report.summary.map((line) => (
                    <li key={line}>{line}</li>
                  ))}
                </ul>
              </section>
            )}
          </section>

          <div className="space-y-6">
            {report && (
              <section aria-labelledby="measure-title" className="card p-4">
                <h2 id="measure-title" className="text-lg font-bold">
                  Measurements
                </h2>
                <dl className="mt-3 grid grid-cols-2 gap-2 text-sm">
                  {[
                    ["Width", `${report.width_mm.toFixed(1)} mm`],
                    ["Depth", `${report.depth_mm.toFixed(1)} mm`],
                    ["Height", `${report.height_mm.toFixed(1)} mm`],
                    ["Scale", `${report.scale_ratio} (1 m = ${report.scale_mm_per_m.toFixed(1)} mm)`],
                    ["Triangles", report.triangle_count.toLocaleString()],
                    ["Volume", `${(report.volume_mm3 / 1000).toFixed(1)} cm³`],
                  ].map(([k, v]) => (
                    <div key={k} className="rounded-md bg-surface-2 p-2">
                      <dt className="text-muted">{k}</dt>
                      <dd className="font-bold">{v}</dd>
                    </div>
                  ))}
                </dl>
                <h3 className="mt-4 font-bold">Print checks</h3>
                <ul className="mt-1 space-y-1 text-sm">
                  {report.checks.map((c) => (
                    <li key={c.name}>
                      <span className={`font-bold ${c.passed ? "text-ok" : "text-danger"}`}>{c.passed ? "✓ Pass" : "✗ Fail"}</span>{" "}
                      {c.detail}
                    </li>
                  ))}
                </ul>
                {report.warnings.length > 0 && (
                  <>
                    <h3 className="mt-4 font-bold">Adjustments made</h3>
                    <ul className="mt-1 list-disc pl-5 text-sm text-muted">
                      {report.warnings.map((w) => (
                        <li key={w}>{w}</li>
                      ))}
                    </ul>
                  </>
                )}
              </section>
            )}

            <section aria-labelledby={`${formId}-title`} className="card p-4">
              <h2 id={`${formId}-title`} className="text-lg font-bold">
                Print settings
              </h2>
              <p className="text-sm text-muted">Prototype defaults. Tune them after a test print.</p>
              <form
                className="mt-3 space-y-3"
                onSubmit={(e) => {
                  e.preventDefault();
                  generate(settings);
                }}
              >
                <div className="grid grid-cols-2 gap-3">
                  {NUMBER_FIELDS.map((f) => (
                    <div key={f.key}>
                      <label htmlFor={`${formId}-${f.key}`} className="field-label">
                        {f.label} <span className="font-normal text-muted">(mm)</span>
                      </label>
                      <input
                        id={`${formId}-${f.key}`}
                        type="number"
                        className="field-input"
                        min={f.min}
                        max={f.max}
                        step={f.step}
                        value={settings[f.key]}
                        onChange={(e) => {
                          const v = parseFloat(e.target.value);
                          if (!Number.isNaN(v)) setSettings({ ...settings, [f.key]: v });
                        }}
                      />
                    </div>
                  ))}
                </div>
                <fieldset>
                  <legend className="field-label">Include</legend>
                  {BOOL_FIELDS.map((f) => (
                    <label key={f.key} className="flex min-h-10 items-center gap-2">
                      <input
                        type="checkbox"
                        className="h-5 w-5 accent-[var(--accent)]"
                        checked={settings[f.key]}
                        onChange={(e) => setSettings({ ...settings, [f.key]: e.target.checked })}
                      />
                      {f.label}
                    </label>
                  ))}
                </fieldset>
                <button type="submit" className="btn-primary w-full" disabled={busy}>
                  {busy ? "Generating…" : settingsChanged ? "Apply settings and regenerate" : "Regenerate with these settings"}
                </button>
              </form>
            </section>
          </div>
        </div>
      </div>
    </div>
  );
}
