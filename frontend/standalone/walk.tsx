/** Self-contained walkthrough with bundled maps. Connected Q&A is available in the main app. */
import { StrictMode, useState } from "react";
import { createRoot } from "react-dom/client";
import "../src/index.css";
import type { FloorMap } from "../src/api/types";
import { WalkthroughView } from "../src/pages/Walkthrough";
import apartment from "./maps/apartment.json";
import demo from "./maps/demo.json";
const MAPS = [
  { id: "demo", label: "Demo building", map: demo as unknown as FloorMap },
  {
    id: "apartment",
    label: "Apartment scan",
    map: apartment as unknown as FloorMap,
  },
];
function StandaloneWalk() {
  const [mapId, setMapId] = useState(MAPS[0].id);
  const entry = MAPS.find((m) => m.id === mapId)!;
  return (
    <>
      <a href="#main" className="skip-link">
        Skip to the walkthrough
      </a>
      <main id="main" tabIndex={-1}>
        <WalkthroughView
          key={entry.id}
          map={entry.map}
          header={
            <select
              aria-label="Choose space"
              className="standalone-space-picker"
              value={mapId}
              onChange={(e) => setMapId(e.target.value)}
            >
              {MAPS.map((m) => (
                <option key={m.id} value={m.id}>
                  {m.label}
                </option>
              ))}
            </select>
          }
        />
      </main>
    </>
  );
}
createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <StandaloneWalk />
  </StrictMode>,
);
