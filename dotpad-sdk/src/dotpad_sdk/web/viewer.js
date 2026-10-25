import {drawPins} from "/pins.js";

const graphics = document.querySelector("#graphics"), braille = document.querySelector("#braille");
const status = document.querySelector("#connection"), error = document.querySelector("#error");
const held = new Set();
let mock = false, lastFrame = "", lastEvents = "";
let buttonQueue = Promise.resolve();

async function post(path, body = {}) {
  const response = await fetch(path, {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(body)});
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || "Request failed");
  return data;
}

function showError(message) { error.textContent = message || ""; error.hidden = !message; }

async function buttonEvent(button, action) {
  if (!mock || (action === "down") === held.has(button)) return;
  if (action === "down") held.add(button); else held.delete(button);
  document.querySelector(`[data-button="${button}"]`).setAttribute("aria-pressed", String(action === "down"));
  buttonQueue = buttonQueue.then(() => post("/api/buttons", {button, action})).catch(e => showError(e.message));
  await buttonQueue;
}

for (const button of document.querySelectorAll("[data-button]")) {
  const key = button.dataset.button;
  button.addEventListener("pointerdown", (event) => {
    if (event.button !== 0) return;
    button.setPointerCapture(event.pointerId);
    buttonEvent(key, "down");
  });
  for (const name of ["pointerup", "pointercancel", "lostpointercapture"]) button.addEventListener(name, () => buttonEvent(key, "up"));
  button.addEventListener("keydown", (event) => {
    if ([" ", "Enter"].includes(event.key)) { event.preventDefault(); if (!event.repeat) buttonEvent(key, "down"); }
  });
  button.addEventListener("keyup", (event) => {
    if ([" ", "Enter"].includes(event.key)) { event.preventDefault(); buttonEvent(key, "up"); }
  });
  button.addEventListener("blur", () => buttonEvent(key, "up"));
}

function releaseAll() { for (const button of [...held]) buttonEvent(button, "up"); }
window.addEventListener("blur", releaseAll);
document.addEventListener("visibilitychange", () => { if (document.hidden) releaseAll(); });
window.addEventListener("pagehide", () => {
  for (const button of held) fetch("/api/buttons", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({button, action: "up"}), keepalive: true}).catch(() => {});
});

for (const button of document.querySelectorAll("[data-command]")) {
  button.addEventListener("click", async () => {
    try { await post(`/api/mock/${button.dataset.command}`); showError(null); }
    catch (e) { showError(e.message); }
  });
}

async function update() {
  try {
    const response = await fetch("/api/state");
    if (!response.ok) throw new Error("Viewer connection lost");
    const state = await response.json(), g = state.geometry;
    status.textContent = state.connected ? (mock ? "Mock connected" : "Device connected") : "Disconnected";
    status.classList.toggle("online", state.connected);
    const frame = JSON.stringify([g, state.graphics_hex, state.braille_hex]);
    if (frame !== lastFrame) {
      drawPins(graphics, state.graphics_hex, g.graphic_columns, g.graphic_rows);
      drawPins(braille, state.braille_hex, g.braille_cells, 1, true);
      lastFrame = frame;
    }
    document.querySelector("#dimensions").textContent = `${g.graphic_columns * 2} × ${g.graphic_rows * 4} graphic pins · ${g.braille_cells} braille cells`;
    document.querySelector("#revision").textContent = `Frame ${state.revision}`;
    const events = state.events.map(e => `${e.button.replace("function", "F").replace("panning_", "")} ${e.action === "down" ? "↓" : "↑"}`).join("  ·  ");
    if (events && events !== lastEvents) { document.querySelector("#event-log").textContent = events; lastEvents = events; }
    for (const button of document.querySelectorAll("[data-button]")) button.disabled = !mock || !state.connected;
  } catch (e) { status.textContent = "Viewer offline"; status.classList.remove("online"); showError(e.message); }
  setTimeout(update, 150);
}

try {
  const config = await (await fetch("/api/config")).json();
  mock = config.mock;
  document.querySelector("#mock-controls").hidden = !mock;
  if (!mock) document.title = "DotPad · Device monitor";
  update();
} catch (e) { showError(e.message); }
