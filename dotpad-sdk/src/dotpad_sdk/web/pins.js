// Same explicit encoding as encoding.py. Columns are physical left/right.
export const GRAPHIC_BITS = [[1, 16], [2, 32], [4, 64], [8, 128]];
export const BRAILLE_BITS = [[1, 8], [2, 16], [4, 32], [64, 128]];

export function decodePins(hex, columns, rows, braille = false) {
  const bits = braille ? BRAILLE_BITS : GRAPHIC_BITS;
  const cells = Array.from({length: hex.length / 2}, (_, i) => parseInt(hex.slice(i * 2, i * 2 + 2), 16));
  return Array.from({length: rows * 4}, (_, y) =>
    Array.from({length: columns * 2}, (_, x) => Boolean(cells[Math.floor(y / 4) * columns + Math.floor(x / 2)] & bits[y % 4][x % 2])));
}

export function drawPins(canvas, hex, columns, rows, braille = false) {
  const grid = decodePins(hex, columns, rows, braille);
  const step = 10, cellGap = braille ? 5 : 1.5, padding = 10;
  const width = columns * (2 * step + cellGap) - cellGap + padding * 2;
  const height = rows * (4 * step + (braille ? 0 : 2)) + padding * 2;
  const scale = 2;
  canvas.width = width * scale;
  canvas.height = height * scale;
  const ctx = canvas.getContext("2d");
  ctx.scale(scale, scale);
  ctx.fillStyle = "#333631";
  ctx.fillRect(0, 0, width, height);
  let raised = 0;
  for (let y = 0; y < grid.length; y++) {
    for (let x = 0; x < grid[y].length; x++) {
      const px = padding + x * step + Math.floor(x / 2) * cellGap + step / 2;
      const py = padding + y * step + Math.floor(y / 4) * (braille ? 0 : 2) + step / 2;
      const up = grid[y][x];
      if (up) raised++;
      ctx.beginPath();
      ctx.arc(px, py + .8, 2.3, 0, Math.PI * 2);
      ctx.fillStyle = up ? "#171d12" : "#242920";
      ctx.fill();
      ctx.beginPath();
      ctx.arc(px, py, up ? 2.2 : 1.7, 0, Math.PI * 2);
      ctx.fillStyle = up ? "#e1e8cf" : "#565d4c";
      ctx.fill();
      if (up) {
        ctx.beginPath(); ctx.arc(px - .5, py - .6, .7, 0, Math.PI * 2);
        ctx.fillStyle = "#f8faef"; ctx.fill();
      }
    }
  }
  canvas.dataset.raised = String(raised);
  canvas.setAttribute("aria-label", `${braille ? "Braille" : "Graphic"} display: ${raised} raised pins, ${columns * rows * 8 - raised} lowered pins`);
  return raised;
}
