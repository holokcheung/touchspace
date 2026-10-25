// Uncontracted English braille. The SDK accepts cell hex; it does not translate text.
const LETTERS = [
  1, 3, 9, 25, 17, 11, 27, 19, 10, 26, 5, 7, 13, 29, 21, 15, 31, 23, 14, 30, 37,
  39, 58, 45, 61, 53,
];
const PUNCTUATION: Record<string, number> = {
  " ": 0,
  ",": 2,
  ";": 6,
  ":": 18,
  ".": 50,
  "!": 22,
  "?": 38,
  "-": 36,
  "'": 4,
};
export function brailleBytes(text: string): number[] {
  const cells: number[] = [];
  let numeric = false;
  for (const ch of text.normalize("NFKD").replace(/[\u0300-\u036f]/g, "")) {
    const unit: number[] = [];
    if (/\d/.test(ch)) {
      if (!numeric) unit.push(60); // number indicator
      unit.push(LETTERS[ch === "0" ? 9 : Number(ch) - 1]);
      numeric = true;
    } else {
      if (numeric && /^[a-j]$/i.test(ch)) unit.push(48); // grade-1 indicator ends numeric mode
      numeric = false;
      if (/^[A-Z]$/.test(ch)) unit.push(32);
      const i = ch.toLowerCase().charCodeAt(0) - 97;
      unit.push(i >= 0 && i < 26 ? LETTERS[i] : (PUNCTUATION[ch] ?? 0));
    }
    cells.push(...unit);
  }
  return cells;
}

/** Pad the line and truncate only between complete characters, preserving indicators. */
export function textCells(text: string, width: number): Uint8Array {
  let fitted = text;
  while (fitted && brailleBytes(fitted).length > width)
    fitted = fitted.slice(0, -1);
  const cells = brailleBytes(fitted);
  return Uint8Array.from([
    ...cells,
    ...Array(Math.max(0, width - cells.length)).fill(0),
  ]);
}

/** Keep the compass suffix even when room names need truncation on a 20-cell line. */
export function statusCells(text: string, width: number): Uint8Array {
  const parts = text.match(/^(.*) ([NSEW]{1,2})$/);
  if (!parts) return textCells(text, width);
  let room = parts[1];
  const suffix = ` ${parts[2]}`;
  while (room && brailleBytes(room + suffix).length > width)
    room = room.slice(0, -1);
  return textCells(room + suffix, width);
}
