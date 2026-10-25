import type { FloorMap } from "../api/types";
import { fmt, planBounds, regionName, roomAt } from "../lib/geometry";

/** Text equivalent of the 2D plan, so nothing essential depends on seeing the drawing. */
export default function PlanDescription({ map }: { map: FloorMap }) {
  const b = planBounds(map);
  const start = map.landmarks.find((l) => l.id === map.start_landmark_id);
  const objects = map.objects.filter((o) => !o.hidden);
  return (
    <div className="space-y-3 text-sm leading-relaxed">
      <p>
        The plan is {fmt(b.max_x - b.min_x)} meters wide (west to east) and{" "}
        {fmt(b.max_y - b.min_y)} meters deep (south to north). North is at the
        top. It has {map.walls.length} wall segments, {map.doors.length} doors
        and {map.openings.length} open passages.
      </p>
      {map.rooms.length > 0 && (
        <p>
          Rooms ({map.rooms.length}): {map.rooms.map((r) => r.name).join(", ")}.
        </p>
      )}
      {map.landmarks.length > 0 ? (
        <>
          <p>Landmarks ({map.landmarks.length}):</p>
          <ul className="list-disc pl-5">
            {map.landmarks.map((l) => {
              const room = roomAt(map, l.position);
              return (
                <li key={l.id}>
                  {l.name} ({l.type}) on the {regionName(map, l.position)}
                  {room && room.name !== l.name ? `, in ${room.name}` : ""}.
                </li>
              );
            })}
          </ul>
        </>
      ) : (
        <p>No landmarks are marked yet.</p>
      )}
      <p>
        {start ? `Starting point: ${start.name}.` : "No starting point is set."}
      </p>
      {objects.length > 0 && (
        <p>
          Mapped objects: {objects.map((o) => o.label ?? o.category).join(", ")}
          .
        </p>
      )}
    </div>
  );
}
