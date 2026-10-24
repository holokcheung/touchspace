import { OrbitControls } from "@react-three/drei";
import { Canvas, useThree } from "@react-three/fiber";
import { forwardRef, useEffect, useImperativeHandle, useMemo, useRef, useState } from "react";
import * as THREE from "three";
import { STLLoader } from "three/examples/jsm/loaders/STLLoader.js";
import type { OrbitControls as OrbitControlsImpl } from "three-stdlib";

export interface ViewerHandle {
  reset: () => void;
  top: () => void;
  zoom: (factor: number) => void;
}

interface Props {
  url: string;
  label: string;
  onError?: (message: string) => void;
}

function useStlGeometry(url: string, onError?: (m: string) => void) {
  const [geometry, setGeometry] = useState<THREE.BufferGeometry | null>(null);
  useEffect(() => {
    let cancelled = false;
    setGeometry(null);
    fetch(url)
      .then((r) => {
        if (!r.ok) throw new Error(`Could not load the model (HTTP ${r.status}).`);
        return r.arrayBuffer();
      })
      .then((buf) => {
        if (cancelled) return;
        const g = new STLLoader().parse(buf);
        g.computeVertexNormals();
        g.computeBoundingBox();
        setGeometry(g);
      })
      .catch((e) => !cancelled && onError?.(e instanceof Error ? e.message : String(e)));
    return () => {
      cancelled = true;
    };
  }, [url, onError]);
  return geometry;
}

const Scene = forwardRef<ViewerHandle, { geometry: THREE.BufferGeometry }>(function Scene({ geometry }, ref) {
  const controls = useRef<OrbitControlsImpl>(null);
  const { camera } = useThree();

  // The STL is Z-up in millimeters; three.js is Y-up. Rotate and center it on the origin.
  const { size, center } = useMemo(() => {
    const box = geometry.boundingBox!;
    return { size: box.getSize(new THREE.Vector3()), center: box.getCenter(new THREE.Vector3()) };
  }, [geometry]);
  const span = Math.max(size.x, size.y);

  const place = (pos: [number, number, number]) => {
    camera.position.set(...pos);
    camera.up.set(0, 1, 0);
    camera.lookAt(0, 0, 0); // controls may not be attached yet on the first render
    controls.current?.target.set(0, 0, 0);
    controls.current?.update();
  };
  const reset = () => place([0, span * 1.05, span * 0.95]);
  const top = () => place([0, span * 1.25, 0.001]);

  useEffect(reset, [span]); // eslint-disable-line react-hooks/exhaustive-deps

  useImperativeHandle(ref, () => ({
    reset,
    top,
    zoom: (factor: number) => {
      const t = controls.current?.target ?? new THREE.Vector3();
      camera.position.sub(t).multiplyScalar(factor).add(t);
      controls.current?.update();
    },
  }));

  return (
    <>
      <hemisphereLight args={["#ffffff", "#6b7076", 0.9]} />
      {/* Low, raking key light so raised edges cast visible shading even from above. */}
      <directionalLight position={[-span, span * 0.6, span * 0.5]} intensity={2.0} />
      <directionalLight position={[span, span * 0.4, -span]} intensity={0.35} />
      <group rotation={[-Math.PI / 2, 0, 0]}>
        <mesh geometry={geometry} position={[-center.x, -center.y, -size.z / 2]}>
          <meshStandardMaterial color="#e8e2d4" roughness={0.65} metalness={0.02} />
        </mesh>
      </group>
      <OrbitControls ref={controls} makeDefault enableDamping minDistance={span * 0.2} maxDistance={span * 3} />
    </>
  );
});

const ModelViewer = forwardRef<ViewerHandle, Props>(function ModelViewer({ url, label, onError }, ref) {
  const geometry = useStlGeometry(url, onError);
  return (
    <div className="relative aspect-[4/3] w-full overflow-hidden rounded-xl border border-line bg-gradient-to-b from-surface-2 to-surface">
      {geometry ? (
        <Canvas camera={{ fov: 40, near: 1, far: 5000 }} aria-label={label} role="img" dpr={[1, 2]}>
          <Scene ref={ref} geometry={geometry} />
        </Canvas>
      ) : (
        <p className="absolute inset-0 grid place-items-center text-muted" role="status">
          Loading 3D model…
        </p>
      )}
    </div>
  );
});

export default ModelViewer;
