/** Same service and default name filter as the vendor's 3.0.4 demo. */
export const DOTPAD_SERVICE = "49535343-fe7d-4ae5-8fa9-9fafd205e455";
export type BluetoothDiscovery = "dotpad" | "all";
interface BluetoothPicker {
  requestDevice(options: {
    filters?: { namePrefix: string }[];
    acceptAllDevices?: boolean;
    optionalServices: string[];
  }): Promise<unknown>;
}

/**
 * Call the browser picker directly because the vendor scanner swallows permission
 * and adapter errors. Connection, framing and display output still use the SDK.
 * No await before requestDevice: it must keep the originating click gesture.
 */
export function selectBluetoothDevice(
  discovery: BluetoothDiscovery = "dotpad",
): Promise<unknown> {
  const bluetooth = (navigator as Navigator & { bluetooth: BluetoothPicker })
    .bluetooth;
  const options =
    discovery === "all"
      ? { acceptAllDevices: true, optionalServices: [DOTPAD_SERVICE] }
      : {
          filters: [{ namePrefix: "DotPad" }],
          optionalServices: [DOTPAD_SERVICE],
        };
  return bluetooth.requestDevice(options).catch((error: unknown) => {
    if (error instanceof DOMException && error.name === "NotFoundError")
      return undefined;
    throw error;
  });
}

export function bluetoothErrorMessage(error: unknown): string {
  const details =
    error && typeof error === "object"
      ? (error as { name?: unknown; message?: unknown })
      : {};
  const name = typeof details.name === "string" ? details.name : "";
  const message = typeof details.message === "string" ? details.message : "";
  if (name === "NotAllowedError" || name === "SecurityError") {
    return `Bluetooth access was blocked for ${window.location.origin}. Allow Bluetooth / nearby devices in this site's Chrome settings. The SDK demo on port 3000 has separate site permissions. ${message}`;
  }
  if (name === "NetworkError") {
    return "Could not reach the DotPad. Disconnect it in the SDK demo or other apps, make sure it is advertising over Bluetooth, and try again.";
  }
  return message || "DotPad Bluetooth connection failed.";
}

export interface KnownDotPad {
  id: string;
  name?: string;
}

/** Browser-granted devices can be listed even when they are no longer advertising. */
export async function knownDotPads(): Promise<KnownDotPad[]> {
  const bluetooth = (
    navigator as Navigator & {
      bluetooth?: { getDevices?: () => Promise<KnownDotPad[]> };
    }
  ).bluetooth;
  if (!bluetooth?.getDevices) return [];
  const devices = await bluetooth.getDevices();
  return devices.filter((device) =>
    /^(DotPad|KM[23]-|DPK|DMI)/i.test(device.name ?? ""),
  );
}
