/**
 * The walk-through as one self-contained page, with no backend: the maps are bundled in.
 * Build with `npm run build:walk`; it writes a single HTML file (see scripts/inline-walk.mjs).
 */
import { StrictMode, useId, useState } from "react";
import { createRoot } from "react-dom/client";
import "../src/index.css";
import type { FloorMap } from "../src/api/types";
import { WalkthroughView } from "../src/pages/Walkthrough";
import apartment from "./maps/apartment.json";
import demo from "./maps/demo.json";

const MAPS = [
  {
    id: "demo",
    label: "Demo building",
    map: demo as unknown as FloorMap,
    note: "A synthetic 16 × 10 meter building made for this demo. It isn't a real place.",
  },
  {
    id: "apartment",
    label: "Real apartment scan",
    map: apartment as unknown as FloorMap,
    note: "A real iPhone RoomPlan scan, published by theLodgeStudio in open3dfloorplan (MIT License). Room names are RoomPlan's unconfirmed guesses.",
  },
];

// The app styles dark mode with a .dark class; follow the viewer's theme (an explicit
// data-theme choice first, then the system setting).
function syncTheme() {
  const root = document.documentElement;
  const choice = root.getAttribute("data-theme");
  const dark = choice ? choice === "dark" : window.matchMedia("(prefers-color-scheme: dark)").matches;
  root.classList.toggle("dark", dark);
}
syncTheme();
window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", syncTheme);
new MutationObserver(syncTheme).observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });

function Header({ mapId, onPick }: { mapId: string; onPick: (id: string) => void }) {
  const ids = useId();
  const current = MAPS.find((m) => m.id === mapId)!;
  return (
    <header className="border-b border-line bg-surface">
      <div className="mx-auto max-w-7xl px-4 py-4">
        <p className="text-sm font-bold text-accent">TouchSpace AI</p>
        <h1 className="text-2xl font-bold">Walk-through</h1>
        <fieldset className="mt-3">
          <legend className="field-label">Map</legend>
          <div className="flex flex-wrap gap-2">
            {MAPS.map((m) => (
              <label
                key={m.id}
                className={`btn min-h-11 cursor-pointer ${m.id === mapId ? "border-accent bg-accent-soft text-text" : "border-line bg-surface text-text"}`}
              >
                <input
                  type="radio"
                  name={`${ids}-map`}
                  value={m.id}
                  checked={m.id === mapId}
                  onChange={() => onPick(m.id)}
                  className="h-4 w-4 accent-[var(--accent)]"
                />
                {m.label}
              </label>
            ))}
          </div>
        </fieldset>
        <p className="mt-2 text-sm text-muted">{current.note}</p>
      </div>
    </header>
  );
}

function StandaloneWalk() {
  const [mapId, setMapId] = useState(MAPS[0].id);
  const entry = MAPS.find((m) => m.id === mapId)!;
  return (
    <>
      <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-10 btn-primary">
        Skip to the walk-through
      </a>
      <main id="main" tabIndex={-1}>
        <WalkthroughView key={entry.id} map={entry.map} header={<Header mapId={mapId} onPick={setMapId} />} />
      </main>
      <footer className="mx-auto max-w-7xl px-4 pb-8 text-sm text-muted">
        Spoken announcements use your device's built-in voice in this version. A travel aid for practice, not a replacement for
        a cane or guide dog.
      </footer>
    </>
  );
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <StandaloneWalk />
  </StrictMode>,
);
