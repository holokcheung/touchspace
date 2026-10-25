import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { DotPadConnection } from "../dotpad/device";
import { statusCells, textCells } from "../dotpad/text";
import { PIN } from "../dotpad/pins";
const sdk = vi.hoisted(() => ({
  callback: null as
    null | ((device: object, code: string, message: string) => void),
  keyCallback: null as
    null | ((device: object, code: string, message: string) => void),
  graphic: vi.fn(),
  text: vi.fn(),
  disconnect: vi.fn(),
  clear: vi.fn(),
  scan: vi.fn(),
  connect: vi.fn(),
}));
vi.mock("../dotpad/vendor/DotPadSDK-3.0.4.js", () => ({
  DataCodes: {
    Connected: "Connected",
    Disconnected: "Disconnected",
    ConnectedFail: "ConnectedFail",
    CommandError: "CommandError",
    ResponseDisplayLineNonAck: "NonAck",
  },
  DisplayMode: { GraphicMode: "GraphicMode", TextMode: "TextMode" },
  DotPadScanner: class {
    startBleScan = sdk.scan;
    startUsbScan = sdk.scan;
  },
  DotPadSDK: class {
    setCallBack(cb: typeof sdk.callback, key: typeof sdk.keyCallback) {
      sdk.callback = cb;
      sdk.keyCallback = key;
    }
    connectBleDevice = sdk.connect;
    connectUsbDevice = sdk.connect;
    displayGraphicData = sdk.graphic;
    displayTextData = sdk.text;
    displayAllDown = sdk.clear;
    disconnect = sdk.disconnect;
  },
}));
const device = {
  isConnect: true,
  numberCellColumns: 30,
  numberCellRows: 10,
  numberBrailleCellColumns: 20,
};
const grid = () => ({ cols: 60, rows: 40, pins: new Uint8Array(2400) });
beforeEach(() => {
  vi.useFakeTimers();
  vi.clearAllMocks();
  vi.stubGlobal("isSecureContext", true);
  Object.defineProperty(navigator, "bluetooth", {
    configurable: true,
    value: { requestDevice: sdk.scan },
  });
  Object.defineProperty(navigator, "serial", { configurable: true, value: {} });
  sdk.scan.mockResolvedValue({});
  sdk.connect.mockResolvedValue(device);
  sdk.text.mockResolvedValue(undefined);
});
afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});
describe("DotPad vendor SDK integration", () => {
  it("maps function buttons to zoom only for the active connection and removes callbacks on disposal", async () => {
    const zoom = vi.fn();
    const connection = new DotPadConnection(vi.fn(), zoom);
    const key = sdk.keyCallback!;
    key(device, "KeyFunction2", "4");
    expect(zoom).not.toHaveBeenCalled();
    await connection.connect("usb");
    sdk.callback!(device, "Connected", "");
    key(device, "KeyFunction2", "4");
    key(device, "KeyFunction1", "8");
    expect(zoom.mock.calls).toEqual([["in"], ["out"]]);
    key(device, "KeyFunction12", "12");
    key({ ...device }, "KeyFunction2", "4");
    connection.disconnect();
    key(device, "KeyFunction2", "4");
    expect(zoom).toHaveBeenCalledTimes(2);
    connection.dispose();
    key(device, "KeyFunction2", "4");
    expect(zoom).toHaveBeenCalledTimes(2);
    expect(sdk.keyCallback).toBeNull();
  });
  it("waits for readiness, sends 300 graphic cells and 20 text cells, and coalesces motion", async () => {
    const state = vi.fn();
    const connection = new DotPadConnection(state);
    const first = grid();
    connection.update(first, "Lobby N");
    await connection.connect("bluetooth");
    expect(sdk.graphic).not.toHaveBeenCalled();
    sdk.callback!(device, "Connected", "");
    expect(state).toHaveBeenLastCalledWith("connected");
    expect(sdk.graphic).toHaveBeenLastCalledWith(
      "00".repeat(300),
      device,
      "GraphicMode",
    );
    expect(sdk.text.mock.calls[0][0]).toHaveLength(40);
    const next = grid();
    next.pins[0] = PIN.wall;
    connection.update(first, "old");
    connection.update(next, "Restroom N");
    await vi.advanceTimersByTimeAsync(150);
    expect(sdk.graphic).toHaveBeenCalledTimes(2);
    expect(sdk.graphic.mock.calls[1][0]).toBe("01" + "00".repeat(299));
    connection.dispose();
    expect(sdk.disconnect).toHaveBeenCalled();
    expect(sdk.callback).toBeNull();
  });
  it("passes the all-device fallback through to Chrome and preserves the SDK connection", async () => {
    const selected = { name: "KM2-300A" };
    sdk.scan.mockResolvedValueOnce(selected);
    const connection = new DotPadConnection(vi.fn());
    await connection.connect("bluetooth", "all");
    expect(sdk.scan).toHaveBeenCalledWith({
      acceptAllDevices: true,
      optionalServices: ["49535343-fe7d-4ae5-8fa9-9fafd205e455"],
    });
    expect(sdk.connect).toHaveBeenCalledWith(selected);
    connection.dispose();
  });
  it("reconnects a known DotPad without requesting another Bluetooth picker", async () => {
    const remembered = { id: "saved-dotpad", name: "DotPad320X_BD35" };
    const connection = new DotPadConnection(vi.fn());
    await connection.reconnectBluetooth(remembered);
    expect(sdk.scan).not.toHaveBeenCalled();
    expect(sdk.connect).toHaveBeenCalledWith(remembered);
    connection.dispose();
  });
  it("shows blocked Bluetooth permissions and allows a later retry", async () => {
    const state = vi.fn();
    sdk.scan.mockRejectedValueOnce(
      new DOMException("Blocked", "SecurityError"),
    );
    const connection = new DotPadConnection(state);
    await connection.connect("bluetooth");
    expect(state).toHaveBeenLastCalledWith(
      "disconnected",
      expect.stringMatching(/Bluetooth access was blocked/),
    );
    expect(sdk.connect).not.toHaveBeenCalled();
    await connection.connect("bluetooth");
    expect(sdk.connect).toHaveBeenCalledOnce();
    connection.dispose();
  });
  it("uses the USB picker and rejects an incompatible board", async () => {
    const state = vi.fn();
    const connection = new DotPadConnection(state);
    await connection.connect("usb");
    sdk.callback!({ ...device, numberCellRows: 12 }, "Connected", "");
    expect(sdk.graphic).not.toHaveBeenCalled();
    expect(state).toHaveBeenLastCalledWith(
      "disconnected",
      expect.stringMatching(/60 × 40/),
    );
    connection.dispose();
  });
  it("recovers from picker cancellation and device disconnect", async () => {
    const state = vi.fn();
    const connection = new DotPadConnection(state);
    sdk.scan.mockResolvedValueOnce(undefined);
    await connection.connect("bluetooth");
    expect(state).toHaveBeenLastCalledWith("disconnected");
    await connection.connect("bluetooth");
    sdk.callback!(device, "Connected", "");
    sdk.callback!(device, "Disconnected", "");
    connection.update(grid(), "Lobby");
    await vi.advanceTimersByTimeAsync(200);
    expect(state).toHaveBeenLastCalledWith("disconnected", undefined);
    expect(sdk.graphic).not.toHaveBeenCalled();
    connection.dispose();
  });
  it("cleans up a connection finishing after the view is disposed", async () => {
    let done!: (value: object) => void;
    sdk.connect.mockReturnValueOnce(
      new Promise((resolve) => {
        done = resolve;
      }),
    );
    const connection = new DotPadConnection(vi.fn());
    const connecting = connection.connect("bluetooth");
    await vi.advanceTimersByTimeAsync(0);
    connection.dispose();
    done(device);
    await connecting;
    expect(sdk.disconnect).toHaveBeenCalledTimes(2);
    expect(sdk.graphic).not.toHaveBeenCalled();
  });
  it("times out an incomplete handshake and allows another attempt", async () => {
    const state = vi.fn();
    const connection = new DotPadConnection(state);
    await connection.connect("usb");
    await vi.advanceTimersByTimeAsync(15000);
    expect(state).toHaveBeenLastCalledWith(
      "disconnected",
      expect.stringMatching(/did not finish connecting/),
    );
    connection.dispose();
  });
});
describe("hardware braille text", () => {
  it("encodes capital and number indicators, punctuation, and pads the whole line", () => {
    expect([...textCells("Ab 12", 9)]).toEqual([32, 1, 3, 0, 60, 1, 3, 0, 0]);
    expect([...textCells("1a", 5)]).toEqual([60, 1, 48, 1, 0]);
    expect([...textCells("A", 1)]).toEqual([0]);
    expect([...statusCells("Central Hallway SE", 20)].slice(-5)).toEqual([
      0, 32, 14, 32, 17,
    ]); // do not cut off an indicator
  });
});
