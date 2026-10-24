import type { LandmarkType } from "../api/types";

export const SYMBOL_NAMES: Partial<Record<LandmarkType, string>> = {
  entrance: "solid triangle",
  exit: "solid square",
  restroom: "solid circle",
  stairs: "three parallel bars",
  elevator: "hollow ring",
  information: "plus sign",
};

/**
 * On-screen version of the tactile symbol, drawn around (0,0) within a box of `size`.
 * Matches backend/app/services/symbols.py so the screen and the print agree.
 * Coordinates are SVG (y down).
 */
export function LandmarkGlyph({ type, size, color }: { type: LandmarkType; size: number; color: string }) {
  const h = size / 2;
  switch (type) {
    case "entrance": {
      const r = h * 1.1;
      const pts = [90, 210, 330]
        .map((a) => {
          const rad = (a * Math.PI) / 180;
          return `${r * Math.cos(rad)},${-(r * Math.sin(rad) - r * 0.25)}`;
        })
        .join(" ");
      return <polygon points={pts} fill={color} />;
    }
    case "exit": {
      const s = size * 0.85;
      return <rect x={-s / 2} y={-s / 2} width={s} height={s} fill={color} />;
    }
    case "restroom":
      return <circle r={h} fill={color} />;
    case "stairs": {
      const bar = size * 0.2;
      const step = (size - bar) / 2;
      return (
        <g fill={color}>
          {[-step, 0, step].map((y) => (
            <rect key={y} x={-h} y={y - bar / 2} width={size} height={bar} />
          ))}
        </g>
      );
    }
    case "elevator":
      return <circle r={h - size * 0.1} fill="none" stroke={color} strokeWidth={size * 0.2} />;
    case "information": {
      const arm = size * 0.3;
      return (
        <g fill={color}>
          <rect x={-h} y={-arm / 2} width={size} height={arm} />
          <rect x={-arm / 2} y={-h} width={arm} height={size} />
        </g>
      );
    }
    default:
      // Named areas without a tactile symbol: outlined diamond.
      return (
        <rect
          x={-h * 0.6}
          y={-h * 0.6}
          width={h * 1.2}
          height={h * 1.2}
          transform="rotate(45)"
          fill="var(--surface)"
          stroke={color}
          strokeWidth={size * 0.12}
        />
      );
  }
}
