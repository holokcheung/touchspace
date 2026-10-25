const status = document.querySelector("#hardware-status"), error = document.querySelector("#error");
const ble = document.querySelector("#ble"), usb = document.querySelector("#usb"), disconnect = document.querySelector("#disconnect");
const session = crypto.randomUUID();
let sdk, scanner, vendor, device = null, running = false, connecting = false;
let buttonQueue = Promise.resolve();

function showError(message) { error.textContent = message || ""; error.hidden = !message; }
async function post(path, body = {}) {
  const response = await fetch(path, {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({session, ...body})});
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || "Bridge request failed");
  return data;
}
function controls() {
  ble.disabled = !sdk || !navigator.bluetooth || Boolean(device) || connecting;
  usb.disabled = !sdk || !navigator.serial || Boolean(device) || connecting;
  disconnect.disabled = !device;
}
async function stop() {
  running = false;
  const previous = device;
  device = null;
  if (previous) sdk.disconnect(previous);
  try { await post("/api/bridge/disconnect"); } catch { /* Already disconnected. */ }
  status.textContent = "Disconnected";
  controls();
}
async function poll() {
  while (running) {
    try {
      const response = await fetch(`/api/bridge/commands?session=${encodeURIComponent(session)}`);
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || "Bridge unavailable");
      for (const command of data.commands) {
        let failure = null;
        try {
          if (!device?.isConnect) throw new Error("DotPad disconnected");
          if (command.area === "graphics") sdk.displayGraphicData(command.hex, device, vendor.DisplayMode.GraphicMode);
          else if (command.area === "braille") await sdk.displayTextData(command.hex, device, vendor.DisplayMode.TextMode, false);
          else throw new Error("Unknown output area");
        } catch (e) { failure = e.message; }
        // Acknowledge SDK submission, not physical pin movement/completion.
        await post("/api/bridge/ack", {id: command.id, error: failure});
      }
    } catch (e) { showError(e.message); await stop(); break; }
    await new Promise(resolve => setTimeout(resolve, 70));
  }
}

async function connect(kind) {
  if (connecting || device) return;
  connecting = true;
  controls();
  showError(null);
  try {
    // The picker must be called directly within this user gesture, before other awaits.
    const selected = await (kind === "ble" ? scanner.startBleScan() : scanner.startUsbScan());
    if (!selected) { status.textContent = "Device selection cancelled"; return; }
    status.textContent = "Connecting…";
    const result = await (kind === "ble" ? sdk.connectBleDevice(selected) : sdk.connectUsbDevice(selected));
    if (!result?.isConnect) throw new Error("DotPad did not become ready");
    device = result;
    await post("/api/bridge/connect", {geometry: {graphic_columns: result.numberCellColumns, graphic_rows: result.numberCellRows, braille_cells: result.numberBrailleCellColumns}});
    running = true;
    status.textContent = "Connected · awaiting Python frames";
    poll();
  } catch (e) { showError(e.message); await stop(); }
  finally { connecting = false; controls(); }
}

ble.addEventListener("click", () => connect("ble"));
usb.addEventListener("click", () => connect("usb"));
disconnect.addEventListener("click", stop);
window.addEventListener("pagehide", () => {
  fetch("/api/bridge/disconnect", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({session}), keepalive: true}).catch(() => {});
});
controls();
try {
  const config = await (await fetch("/api/config")).json();
  if (!config.browser) throw new Error("Start the gateway with BrowserBackend to use hardware bridging");
  if (!config.web_sdk_available) throw new Error("Supply --web-sdk /path/to/DotPadSDK-3.0.4.js when starting the viewer");
  vendor = await import("/vendor-sdk.js");
  sdk = new vendor.DotPadSDK(); scanner = new vendor.DotPadScanner();
  const keyMap = {KeyFunction1: "function1", KeyFunction2: "function2", KeyFunction3: "function3", KeyFunction4: "function4", PanningLeft: "panning_left", PanningRight: "panning_right"};
  function keyEvent(source, key, action) {
    if (source === device && keyMap[key]) buttonQueue = buttonQueue.then(() => post("/api/bridge/button", {button: keyMap[key], action})).catch(e => showError(e.message));
  }
  sdk.setCallBack((source, code) => {
    if (source === device && code === vendor.DataCodes.Disconnected) stop();
  }, null, (source, key) => keyEvent(source, key, "down"), (source, key) => keyEvent(source, key, "up"));
  status.textContent = "Choose a connection. Chrome/Chromium hardware API support is required.";
} catch (e) { showError(e.message); status.textContent = "Hardware bridge unavailable"; }
controls();
