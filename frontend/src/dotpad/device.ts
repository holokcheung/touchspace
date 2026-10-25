import {
  DataCodes,
  DisplayMode,
  DotPadScanner,
  DotPadSDK,
  type DotDevice,
} from "./vendor/DotPadSDK-3.0.0.js";
import { DOTPAD, toCellBytes, toHex, type PinGrid } from "./pins";
import { statusCells } from "./text";

export type DeviceState = "disconnected" | "connecting" | "connected";
export type Transport = "bluetooth" | "usb";
export function supportedTransports(): Transport[] {
  if (!window.isSecureContext) return [];
  return ["bluetooth", "usb"].filter(
    (t) => (t === "bluetooth" ? "bluetooth" : "serial") in navigator,
  ) as Transport[];
}

/** Owns one SDK connection. Latest frame wins; the SDK manages line ACKs and diffs. */
export class DotPadConnection {
  private sdk = new DotPadSDK();
  private scanner = new DotPadScanner();
  private device: DotDevice | null = null;
  private state: DeviceState = "disconnected";
  private disposed = false;
  private timer: ReturnType<typeof setTimeout> | null = null;
  private handshake: ReturnType<typeof setTimeout> | null = null;
  private latest: { grid: PinGrid; text: string } | null = null;

  constructor(private onState: (state: DeviceState, error?: string) => void) {
    this.sdk.setCallBack((device, code) => {
      if (this.disposed) return;
      if (code === DataCodes.Connected) {
        if (this.handshake) clearTimeout(this.handshake);
        this.device = device;
        if (
          device.numberCellColumns !== DOTPAD.cols / 2 ||
          device.numberCellRows !== DOTPAD.rows / 4
        ) {
          this.disconnect();
          this.onState(
            "disconnected",
            "This map requires a DotPad with a 60 × 40 pin graphic area.",
          );
          return;
        }
        this.state = "connected";
        this.onState(this.state);
        this.flush();
      } else if (
        code === DataCodes.Disconnected ||
        code === DataCodes.ConnectedFail
      ) {
        if (this.handshake) clearTimeout(this.handshake);
        if (this.timer) clearTimeout(this.timer);
        this.handshake = this.timer = null;
        this.device = null;
        this.state = "disconnected";
        this.onState(
          this.state,
          code === DataCodes.ConnectedFail
            ? "Could not connect to the DotPad. Try again."
            : undefined,
        );
      } else if (
        code === DataCodes.CommandError ||
        code === DataCodes.ResponseDisplayLineNonAck
      ) {
        this.onState(
          this.state,
          "The DotPad did not accept the display data. Reconnect to try again.",
        );
      }
    }, null);
  }

  private isDisconnected(): boolean {
    return this.state === "disconnected";
  }

  async connect(transport: Transport): Promise<void> {
    if (this.disposed || this.state !== "disconnected") return;
    if (!supportedTransports().includes(transport)) {
      this.onState(
        "disconnected",
        "Use Chrome with HTTPS or localhost to connect a DotPad.",
      );
      return;
    }
    this.state = "connecting";
    this.onState(this.state);
    try {
      // Keep the picker in the originating button gesture (no lazy import before it).
      const selected = await (transport === "bluetooth"
        ? this.scanner.startBleScan()
        : this.scanner.startUsbScan());
      if (this.disposed) return;
      if (!selected) {
        this.disconnect();
        return;
      }
      this.handshake = setTimeout(() => {
        this.disconnect();
        this.onState(
          "disconnected",
          "The DotPad did not finish connecting. Check its power and try again.",
        );
      }, 15000);
      const device = await (transport === "bluetooth"
        ? this.sdk.connectBleDevice(selected)
        : this.sdk.connectUsbDevice(selected));
      if (this.disposed || this.isDisconnected()) {
        this.sdk.disconnect();
        return;
      }
      if (!device)
        throw new Error(
          "Could not connect to the DotPad. Check its power and try again.",
        );
      // The Connected callback, rather than the transport return, marks readiness.
    } catch (error) {
      this.disconnect();
      if (!this.disposed)
        this.onState(
          "disconnected",
          error instanceof Error ? error.message : "DotPad connection failed.",
        );
    }
  }

  update(grid: PinGrid, text: string): void {
    this.latest = { grid, text };
    if (this.state === "connected" && !this.timer)
      this.timer = setTimeout(() => {
        this.timer = null;
        this.flush();
      }, 150);
  }

  private flush(): void {
    if (!this.device || !this.latest || this.state !== "connected") return;
    try {
      this.sdk.displayGraphicData(
        toHex(toCellBytes(this.latest.grid)),
        this.device,
        DisplayMode.GraphicMode,
      );
      const cells = this.device.numberBrailleCellColumns;
      if (cells > 0)
        this.sdk.displayTextData(
          toHex(statusCells(this.latest.text, cells)),
          this.device,
          DisplayMode.TextMode,
        );
    } catch {
      this.onState(
        this.state,
        "Could not update the DotPad. Reconnect to try again.",
      );
    }
  }

  clear(): void {
    if (this.device) this.sdk.displayAllDown(this.device);
  }
  disconnect(): void {
    if (this.timer) clearTimeout(this.timer);
    if (this.handshake) clearTimeout(this.handshake);
    this.timer = this.handshake = null;
    this.sdk.disconnect();
    this.device = null;
    this.state = "disconnected";
    if (!this.disposed) this.onState(this.state);
  }
  dispose(): void {
    this.disposed = true;
    this.disconnect();
    this.sdk.setCallBack(null, null);
  }
}
