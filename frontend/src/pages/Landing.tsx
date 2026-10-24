import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../api/client";
import { Notice } from "../components/Status";

const STEPS = [
  {
    title: "Scan your space",
    body: "Walk a room with a LiDAR iPhone or iPad. Apple RoomPlan captures walls, doors, openings and furniture, and the TouchSpace scanner exports it as JSON.",
  },
  {
    title: "Generate a tactile map",
    body: "We clean up the floor plan, keep doorways open, add standard landmark symbols and a legend, and produce a watertight STL ready for any FDM printer.",
  },
  {
    title: "Explore with voice",
    body: "Ask where the restroom is or how to get to the exit. Answers come only from the map's verified landmarks and walkable paths.",
  },
];

export default function Landing() {
  const navigate = useNavigate();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function startDemo() {
    setBusy(true);
    setError(null);
    try {
      const res = await api.createDemo();
      navigate(`/maps/${res.map.id}/edit`);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setBusy(false);
    }
  }

  return (
    <div className="mx-auto max-w-6xl px-4 py-12 sm:py-20">
      <section aria-labelledby="hero-title" className="max-w-3xl">
        <h1 id="hero-title" className="text-4xl font-bold tracking-tight sm:text-6xl">
          TouchSpace AI
        </h1>
        <p className="mt-4 text-2xl font-bold text-accent sm:text-3xl">
          Scan a Space. Feel the Layout. Explore with Confidence.
        </p>
        <p className="mt-6 text-lg text-muted sm:text-xl">
          Transform real indoor environments into accessible, 3D-printable tactile maps with AI-powered voice
          assistance.
        </p>
        <div className="mt-8 flex flex-wrap gap-3">
          <Link to="/upload" className="btn-primary px-6 text-lg">
            Get Started
          </Link>
          <button type="button" className="btn-secondary px-6 text-lg" onClick={startDemo} disabled={busy}>
            {busy ? "Loading demo…" : "Try Demo"}
          </button>
        </div>
        <p className="mt-3 text-sm text-muted">
          The demo uses a synthetic floor plan we made up. It is not a scan of a real building.
        </p>
        {error && (
          <div className="mt-4">
            <Notice tone="error" title="Could not start the demo">
              {error}
            </Notice>
          </div>
        )}
      </section>

      <section aria-labelledby="how-title" className="mt-16">
        <h2 id="how-title" className="text-2xl font-bold">
          How it works
        </h2>
        <ol className="mt-6 grid gap-4 md:grid-cols-3">
          {STEPS.map((s, i) => (
            <li key={s.title} className="card p-6">
              <p className="text-sm font-bold uppercase tracking-wide text-accent">Step {i + 1}</p>
              <h3 className="mt-2 text-xl font-bold">{s.title}</h3>
              <p className="mt-2 text-muted">{s.body}</p>
            </li>
          ))}
        </ol>
      </section>

      <section aria-labelledby="symbols-title" className="mt-16">
        <h2 id="symbols-title" className="text-2xl font-bold">
          Tactile symbol key
        </h2>
        <p className="mt-2 max-w-3xl text-muted">
          Symbols differ in shape, not just size, so they can be told apart by touch. These are prototype choices
          that still need testing with tactile map readers.
        </p>
        <dl className="mt-4 grid grid-cols-2 gap-x-6 gap-y-2 sm:grid-cols-3">
          {[
            ["Solid triangle", "Entrance"],
            ["Solid square", "Exit"],
            ["Solid circle", "Restroom"],
            ["Three parallel bars", "Stairs"],
            ["Hollow ring", "Elevator"],
            ["Plus sign", "Information"],
          ].map(([shape, meaning]) => (
            <div key={shape} className="flex gap-2">
              <dt className="font-bold">{shape}:</dt>
              <dd>{meaning}</dd>
            </div>
          ))}
        </dl>
      </section>
    </div>
  );
}
