import { NavLink } from "react-router-dom";
import type { FloorMap } from "../api/types";

const tab = ({ isActive }: { isActive: boolean }) =>
  `rounded-t-lg border-b-4 px-4 py-2 font-semibold ${isActive ? "border-accent text-text" : "border-transparent text-muted hover:text-text"}`;

export default function MapNav({ map }: { map: FloorMap }) {
  return (
    <div className="border-b border-line bg-surface">
      <div className="mx-auto max-w-7xl px-4 pt-4">
        <p className="text-sm text-muted">
          Current map{map.source.kind === "synthetic" ? " (synthetic demo, not a real scan)" : ""}
        </p>
        <h1 className="text-2xl font-bold">{map.name}</h1>
        <nav aria-label="Map views" className="mt-3 flex flex-wrap gap-1">
          <NavLink to={`/maps/${map.id}/edit`} className={tab}>
            Floor plan
          </NavLink>
          <NavLink to={`/maps/${map.id}/preview`} className={tab}>
            3D tactile map
          </NavLink>
          <NavLink to={`/maps/${map.id}/voice`} className={tab}>
            Voice explorer
          </NavLink>
          <NavLink to={`/maps/${map.id}/walk`} className={tab}>
            Walk-through
          </NavLink>
        </nav>
      </div>
    </div>
  );
}
