import { useMemo } from "react";
import { Canvas, useFrame } from "@react-three/fiber";
import { Html, Line } from "@react-three/drei";
import { Euler, Quaternion, Shape, Vector3 } from "three";
import type { FloorMap, Point2D, Room } from "../api/types";
import { dist, planBounds, wallPieces } from "../lib/geometry";
import type { Pose } from "../lib/soundscape";

function Camera({ pose }: { pose: Pose }) {
  const target = useMemo(() => new Vector3(), []);
  const rotation = useMemo(() => new Quaternion(), []);
  const euler = useMemo(() => new Euler(), []);
  const reduced = window.matchMedia?.(
    "(prefers-reduced-motion: reduce)",
  ).matches;
  useFrame(({ camera }, delta) => {
    target.set(pose.position.x, 1.62, -pose.position.y);
    rotation.setFromEuler(euler.set(0, (-pose.heading * Math.PI) / 180, 0));
    const amount = reduced ? 1 : 1 - Math.exp(-14 * delta);
    camera.position.lerp(target, amount);
    camera.quaternion.slerp(rotation, amount);
  });
  return null;
}

function RoomFloor({ room, index }: { room: Room; index: number }) {
  const shape = useMemo(() => {
    const s = new Shape();
    room.polygon.forEach((p, i) =>
      i ? s.lineTo(p.x, p.y) : s.moveTo(p.x, p.y),
    );
    s.closePath();
    return s;
  }, [room]);
  return (
    <mesh
      rotation={[-Math.PI / 2, 0, 0]}
      position={[0, 0.012, 0]}
      receiveShadow
    >
      <shapeGeometry args={[shape]} />
      <meshStandardMaterial
        color={["#ddd8c9", "#c9d5d0", "#d1d4c7"][index % 3]}
        roughness={0.95}
      />
    </mesh>
  );
}

function Space({
  map,
  pose,
  route,
}: {
  map: FloorMap;
  pose: Pose;
  route?: Point2D[];
}) {
  const bounds = planBounds(map);
  const gaps = [...map.doors, ...map.openings];
  return (
    <>
      <color attach="background" args={["#b9c8c5"]} />
      <fog attach="fog" args={["#b9c8c5", 22, 65]} />
      <hemisphereLight args={["#fff8e9", "#596e68", 2.2]} />
      <directionalLight
        position={[bounds.min_x + 4, 12, -bounds.max_y + 3]}
        intensity={2.4}
        castShadow
        shadow-mapSize={[2048, 2048]}
        shadow-camera-left={-25}
        shadow-camera-right={25}
        shadow-camera-top={25}
        shadow-camera-bottom={-25}
      />
      <mesh
        rotation={[-Math.PI / 2, 0, 0]}
        position={[
          (bounds.min_x + bounds.max_x) / 2,
          -0.01,
          -(bounds.min_y + bounds.max_y) / 2,
        ]}
        receiveShadow
      >
        <planeGeometry
          args={[
            Math.max(100, bounds.max_x - bounds.min_x + 20),
            Math.max(100, bounds.max_y - bounds.min_y + 20),
          ]}
        />
        <meshStandardMaterial color="#aabbb3" roughness={1} />
      </mesh>
      {map.rooms
        .filter((r) => r.polygon.length >= 3)
        .map((r, i) => (
          <RoomFloor key={r.id} room={r} index={i} />
        ))}
      {map.walls.flatMap((wall) => {
        const own = gaps.filter((g) => g.wall_id === wall.id);
        const height = Math.max(2.2, wall.height ?? 2.7);
        const beam = (
          a: Point2D,
          b: Point2D,
          bottom: number,
          h: number,
          key: string,
        ) => (
          <group
            key={key}
            position={[(a.x + b.x) / 2, bottom + h / 2, -(a.y + b.y) / 2]}
            rotation={[0, Math.atan2(b.y - a.y, b.x - a.x), 0]}
          >
            <mesh castShadow receiveShadow>
              <boxGeometry
                args={[dist(a, b), h, Math.max(wall.thickness, 0.12)]}
              />
              <meshStandardMaterial color="#f1eddf" roughness={0.85} />
            </mesh>
            {bottom === 0 && (
              <mesh position={[0, -h / 2 + 0.055, 0]}>
                <boxGeometry
                  args={[
                    dist(a, b),
                    0.11,
                    Math.max(wall.thickness, 0.12) + 0.025,
                  ]}
                />
                <meshStandardMaterial color="#71877f" />
              </mesh>
            )}
          </group>
        );
        return [
          ...wallPieces(wall, own).map(([a, b], i) =>
            beam(a, b, 0, height, `${wall.id}-${i}`),
          ),
          ...(own.length
            ? [
                beam(
                  wall.start,
                  wall.end,
                  2.1,
                  Math.max(0.1, height - 2.1),
                  `${wall.id}-header`,
                ),
              ]
            : []),
        ];
      })}
      {map.objects
        .filter((o) => !o.hidden)
        .map((o) => {
          const height = Math.min(
            2.3,
            Math.max(
              0.25,
              o.height ?? (/table|desk/.test(o.category) ? 0.75 : 0.85),
            ),
          );
          return (
            <group
              key={o.id}
              position={[o.position.x, height / 2, -o.position.y]}
              rotation={[0, o.rotation, 0]}
            >
              <mesh castShadow receiveShadow>
                <boxGeometry args={[o.width, height, o.depth]} />
                <meshStandardMaterial
                  color={
                    /bed|sofa|chair/.test(o.category) ? "#829c93" : "#b59c7c"
                  }
                  roughness={0.9}
                />
              </mesh>
              <mesh position={[0, height / 2 + 0.015, 0]}>
                <boxGeometry args={[o.width + 0.025, 0.03, o.depth + 0.025]} />
                <meshStandardMaterial
                  color={
                    /bed|sofa|chair/.test(o.category) ? "#a8bdb1" : "#ceb99b"
                  }
                />
              </mesh>
            </group>
          );
        })}
      {map.landmarks.map((l) => (
        <group key={l.id} position={[l.position.x, 0, -l.position.y]}>
          <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, 0.035, 0]}>
            <ringGeometry args={[0.19, 0.24, 32]} />
            <meshBasicMaterial color="#b88632" />
          </mesh>
          {dist(l.position, pose.position) > 0.8 && (
            <Html
              position={[0, 1.8, 0]}
              center
              distanceFactor={8}
              occlude
              style={{ pointerEvents: "none" }}
            >
              <span className="scene-label">{l.name}</span>
            </Html>
          )}
        </group>
      ))}
      {route && route.length > 1 && (
        <Line
          points={route.map(
            (p) => [p.x, 0.06, -p.y] as [number, number, number],
          )}
          color="#b97c1d"
          lineWidth={5}
          dashed
          dashSize={0.3}
          gapSize={0.15}
        />
      )}
    </>
  );
}

export default function WalkthroughScene({
  map,
  pose,
  route,
}: {
  map: FloorMap;
  pose: Pose;
  route?: Point2D[];
}) {
  return (
    <Canvas
      shadows
      dpr={[1, 1.75]}
      camera={{
        fov: 72,
        near: 0.06,
        far: 150,
        position: [pose.position.x, 1.62, -pose.position.y],
        rotation: [0, (-pose.heading * Math.PI) / 180, 0],
      }}
      fallback={
        <p className="scene-fallback">
          3D is unavailable. You can still walk using the controls, floor plan
          and audio guidance.
        </p>
      }
    >
      <Camera pose={pose} />
      <Space map={map} pose={pose} route={route} />
    </Canvas>
  );
}
