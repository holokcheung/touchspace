import { memo } from "react";
import {
  PIN,
  PIN_SYMBOLS,
  WALKER_SYMBOL,
  describeGrid,
  previewBraille,
  type PinGrid,
} from "./pins";

const FILL: Record<number, string> = {
  [PIN.wall]: "var(--text)",
  [PIN.symbol]: "var(--plan-landmark)",
  [PIN.walker]: "var(--accent)",
  [PIN.route]: "#b97c1d",
};

/** The pins as dots: raised ones large and colored by what raised them, flat ones faint. */
const PinField = memo(function PinField({ grid }: { grid: PinGrid }) {
  const dots = [];
  for (let r = 0; r < grid.rows; r++) {
    for (let c = 0; c < grid.cols; c++) {
      const kind = grid.pins[r * grid.cols + c];
      dots.push(
        kind === PIN.empty ? (
          <circle
            key={r * grid.cols + c}
            cx={c + 0.5}
            cy={r + 0.5}
            r={0.13}
            fill="var(--border)"
          />
        ) : (
          <circle
            key={r * grid.cols + c}
            cx={c + 0.5}
            cy={r + 0.5}
            r={0.4}
            fill={FILL[kind]}
          />
        ),
      );
    }
  }
  return <>{dots}</>;
});

function MiniPattern({
  pattern,
  color,
}: {
  pattern: boolean[][];
  color: string;
}) {
  return (
    <svg viewBox="0 0 3 3" className="h-6 w-6 shrink-0" aria-hidden="true">
      {pattern.flatMap((row, r) =>
        row.map((on, c) => (
          <circle
            key={`${r}-${c}`}
            cx={c + 0.5}
            cy={r + 0.5}
            r={on ? 0.4 : 0.13}
            fill={on ? color : "var(--border)"}
          />
        )),
      )}
    </svg>
  );
}

interface Props {
  grid: PinGrid;
  walker: { col: number; row: number } | null;
  text: string;
  metersPerPin: number;
  routeName?: string;
}

export default function DotPadPreview({
  grid,
  walker,
  text,
  metersPerPin,
  routeName,
}: Props) {
  const counts = describeGrid(grid);
  const label =
    `DotPad preview, ${grid.cols} by ${grid.rows} pins, north up, about ${metersPerPin.toFixed(2)} meters per pin. ` +
    `${counts.walls} wall pins and ${counts.symbols} symbol pins are raised.` +
    (routeName ? ` Route to ${routeName}: ${counts.route} route pins visible.` : "") +
    (walker
      ? ` Your X is at column ${walker.col + 1}, row ${walker.row + 1}.`
      : "") +
    (text ? ` Text line: ${text}.` : "");

  return (
    <div>
      <svg
        viewBox={`0 0 ${grid.cols} ${grid.rows}`}
        className="h-auto w-full rounded-lg bg-surface-2"
        role="img"
        aria-label={label}
      >
        <PinField grid={grid} />
      </svg>

      <div className="mt-2 flex flex-wrap items-center gap-2">
        <span className="text-sm font-bold">Text line</span>
        <span
          className="rounded-md border border-line px-2 py-1 font-mono text-lg tracking-widest"
          aria-hidden="true"
        >
          {previewBraille(text)}
        </span>
        <span className="text-sm">{text || "—"}</span>
      </div>

      <details className="mt-3">
        <summary className="cursor-pointer font-semibold">
          What the pins mean
        </summary>
        <ul className="mt-2 grid gap-2 sm:grid-cols-2">
          <li className="flex items-center gap-2">
            <svg
              viewBox="0 0 3 1"
              className="h-2 w-6 shrink-0"
              aria-hidden="true"
            >
              {[0, 1, 2].map((c) => (
                <circle
                  key={c}
                  cx={c + 0.5}
                  cy={0.5}
                  r={0.4}
                  fill="var(--text)"
                />
              ))}
            </svg>
            Wall: a line of raised pins; a gap is a doorway
          </li>
          <li className="flex items-center gap-2">
            <svg viewBox="0 0 7 1" className="h-2 w-6 shrink-0" aria-hidden="true">
              {[0, 3, 6].map((c) => (
                <circle key={c} cx={c + 0.5} cy={0.5} r={0.4} fill={FILL[PIN.route]} />
              ))}
            </svg>
            Route: spaced raised dots, with gaps beside walls and symbols
          </li>
          <li className="flex items-center gap-2">
            <MiniPattern
              pattern={WALKER_SYMBOL.pattern}
              color="var(--accent)"
            />
            You: an {WALKER_SYMBOL.name}
          </li>
          {Object.entries(PIN_SYMBOLS).map(([type, s]) => (
            <li key={type} className="flex items-center gap-2">
              <MiniPattern pattern={s!.pattern} color="var(--plan-landmark)" />
              <span>
                {type[0].toUpperCase() + type.slice(1)}: {s!.name}
              </span>
            </li>
          ))}
        </ul>
      </details>
    </div>
  );
}
