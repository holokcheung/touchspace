import { memo, useId, useRef, useState } from "react";
import { PIN, PIN_SYMBOLS, WALKER_SYMBOL, describeGrid, previewBraille, toCellBytes, toHex, type PinGrid } from "../lib/dotpad";

const FILL: Record<number, string> = {
  [PIN.wall]: "var(--text)",
  [PIN.symbol]: "var(--plan-landmark)",
  [PIN.walker]: "var(--accent)",
};

/** The pins as dots: raised ones large and colored by what raised them, flat ones faint. */
const PinField = memo(function PinField({ grid }: { grid: PinGrid }) {
  const dots = [];
  for (let r = 0; r < grid.rows; r++) {
    for (let c = 0; c < grid.cols; c++) {
      const kind = grid.pins[r * grid.cols + c];
      dots.push(
        kind === PIN.empty ? (
          <circle key={r * grid.cols + c} cx={c + 0.5} cy={r + 0.5} r={0.13} fill="var(--border)" />
        ) : (
          <circle key={r * grid.cols + c} cx={c + 0.5} cy={r + 0.5} r={0.4} fill={FILL[kind]} />
        ),
      );
    }
  }
  return <>{dots}</>;
});

function MiniPattern({ pattern, color }: { pattern: boolean[][]; color: string }) {
  return (
    <svg viewBox="0 0 3 3" className="h-6 w-6 shrink-0" aria-hidden="true">
      {pattern.flatMap((row, r) =>
        row.map((on, c) => (
          <circle key={`${r}-${c}`} cx={c + 0.5} cy={r + 0.5} r={on ? 0.4 : 0.13} fill={on ? color : "var(--border)"} />
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
}

export default function DotPadPreview({ grid, walker, text, metersPerPin }: Props) {
  const ids = useId();
  const [copied, setCopied] = useState("");
  const hexRef = useRef<HTMLTextAreaElement>(null);
  const counts = describeGrid(grid);
  const hex = toHex(toCellBytes(grid));
  const label =
    `DotPad preview, ${grid.cols} by ${grid.rows} pins, north up, about ${metersPerPin.toFixed(2)} meters per pin. ` +
    `${counts.walls} wall pins and ${counts.symbols} symbol pins are raised.` +
    (walker ? ` Your X is at column ${walker.col + 1}, row ${walker.row + 1}.` : "") +
    (text ? ` Text line: ${text}.` : "");

  async function copyHex() {
    try {
      await navigator.clipboard.writeText(hex);
      setCopied("Pin data copied.");
    } catch {
      hexRef.current?.select();
      setCopied("Couldn't copy automatically; the pin data is selected, so press Copy.");
    }
  }

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
        <span className="rounded-md border border-line px-2 py-1 font-mono text-lg tracking-widest" aria-hidden="true">
          {previewBraille(text)}
        </span>
        <span className="text-sm">{text || "—"}</span>
      </div>

      <details className="mt-3">
        <summary className="cursor-pointer font-semibold">What the pins mean</summary>
        <ul className="mt-2 grid gap-2 sm:grid-cols-2">
          <li className="flex items-center gap-2">
            <svg viewBox="0 0 3 1" className="h-2 w-6 shrink-0" aria-hidden="true">
              {[0, 1, 2].map((c) => (
                <circle key={c} cx={c + 0.5} cy={0.5} r={0.4} fill="var(--text)" />
              ))}
            </svg>
            Wall: a line of raised pins; a gap is a doorway
          </li>
          <li className="flex items-center gap-2">
            <MiniPattern pattern={WALKER_SYMBOL.pattern} color="var(--accent)" />
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

      <details className="mt-2">
        <summary className="cursor-pointer font-semibold">Pin data for testing the DotPad SDK</summary>
        <p className="mt-2 text-sm text-muted">
          {(grid.cols / 2) * (grid.rows / 4)} bytes, one per 2 × 4 braille cell, row by row, in standard braille dot order. Check
          the order against the SDK's own example before relying on it.
        </p>
        <label htmlFor={`${ids}-hex`} className="field-label mt-2">
          Hex
        </label>
        <textarea id={`${ids}-hex`} ref={hexRef} readOnly value={hex} rows={3} className="field-input font-mono text-xs" />
        <div className="mt-2 flex items-center gap-3">
          <button type="button" className="btn-secondary" onClick={copyHex}>
            Copy pin data
          </button>
          <span aria-live="polite" className="text-sm text-muted">
            {copied}
          </span>
        </div>
      </details>
    </div>
  );
}
