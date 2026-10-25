// Narrow declarations for the unmodified vendor ES module. See ../README.md.
export const DataCodes: Record<string, string>;
export const DisplayMode: { GraphicMode: string; TextMode: string };
export interface DotDevice {
  readonly isConnect: boolean;
  readonly numberCellRows: number;
  readonly numberCellColumns: number;
  readonly numberBrailleCellColumns: number;
}
export class DotPadScanner {
  startBleScan(): Promise<unknown>;
  startUsbScan(): Promise<unknown>;
}
export class DotPadSDK {
  setCallBack(
    message:
      ((device: DotDevice, code: string, message: string) => void) | null,
    key: ((device: DotDevice, code: string, message: string) => void) | null,
  ): void;
  connectBleDevice(device: unknown): Promise<DotDevice | null | undefined>;
  connectUsbDevice(port: unknown): Promise<DotDevice | null | undefined>;
  displayGraphicData(hex: string, device: DotDevice, mode: string): void;
  displayTextData(hex: string, device: DotDevice, mode: string): Promise<void>;
  displayAllDown(device: DotDevice): void;
  disconnect(device?: DotDevice): void;
}
