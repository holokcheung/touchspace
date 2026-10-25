import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { DotPadScanner } from "../dotpad/vendor/DotPadSDK-3.0.4.js";
import {
  bluetoothErrorMessage,
  DOTPAD_SERVICE,
  knownDotPads,
  selectBluetoothDevice,
} from "../dotpad/discovery";

const requestDevice = vi.fn();
beforeEach(() => {
  requestDevice.mockReset();
  Object.defineProperty(navigator, "bluetooth", {
    configurable: true,
    value: { requestDevice },
  });
});
afterEach(() => {
  delete (navigator as Navigator & { bluetooth?: unknown }).bluetooth;
});

describe("real Bluetooth picker path", () => {
  it("uses exactly the same request as the working vendor 3.0.4 scanner", async () => {
    const selected = { name: "DotPad320" };
    requestDevice.mockResolvedValue(selected);
    expect(await new DotPadScanner().startBleScan()).toBe(selected);
    const vendorOptions = requestDevice.mock.calls[0][0];
    requestDevice.mockClear();
    const selecting = selectBluetoothDevice();
    // The API is called synchronously, while the originating click is still active.
    expect(requestDevice).toHaveBeenCalledOnce();
    expect(requestDevice).toHaveBeenCalledWith(vendorOptions);
    expect(vendorOptions).toEqual({
      filters: [{ namePrefix: "DotPad" }],
      optionalServices: [DOTPAD_SERVICE],
    });
    expect(await selecting).toBe(selected);
  });

  it("can discover devices whose advertised name does not match DotPad", async () => {
    const device = { name: "KM2-300A" };
    requestDevice.mockImplementation(async (options) => {
      if (!options.acceptAllDevices)
        throw new DOMException("No matching device", "NotFoundError");
      return device;
    });
    expect(await selectBluetoothDevice()).toBeUndefined();
    expect(await selectBluetoothDevice("all")).toBe(device);
    expect(requestDevice).toHaveBeenLastCalledWith({
      acceptAllDevices: true,
      optionalServices: [DOTPAD_SERVICE],
    });
    expect(requestDevice.mock.calls[1][0]).not.toHaveProperty("filters");
  });

  it("preserves permission errors instead of silently treating them as cancellation", async () => {
    const denied = new DOMException(
      "User denied Bluetooth permission",
      "NotAllowedError",
    );
    requestDevice.mockRejectedValue(denied);
    await expect(selectBluetoothDevice()).rejects.toBe(denied);
    expect(bluetoothErrorMessage(denied)).toContain(window.location.origin);
    expect(bluetoothErrorMessage(denied)).toContain(
      "separate site permissions",
    );
  });

  it("treats cancellation as normal and gives connection failures actionable context", async () => {
    requestDevice.mockRejectedValue(
      new DOMException("User cancelled", "NotFoundError"),
    );
    expect(await selectBluetoothDevice()).toBeUndefined();
    expect(
      bluetoothErrorMessage(
        new DOMException("Connection failed", "NetworkError"),
      ),
    ).toMatch(/Disconnect it in the SDK demo/);
  });
});

describe("remembered DotPads", () => {
  it("lists already-authorized devices without starting another discovery scan", async () => {
    const dotpad = { id: "saved-dotpad", name: "DotPad320X_BD35" };
    const getDevices = vi
      .fn()
      .mockResolvedValue([dotpad, { id: "other", name: "Headphones" }]);
    Object.defineProperty(navigator, "bluetooth", {
      configurable: true,
      value: { requestDevice, getDevices },
    });
    expect(await knownDotPads()).toEqual([dotpad]);
    expect(getDevices).toHaveBeenCalledOnce();
    expect(requestDevice).not.toHaveBeenCalled();
  });
  it("keeps scanning available on browsers without remembered-device support", async () => {
    expect(await knownDotPads()).toEqual([]);
    expect(requestDevice).not.toHaveBeenCalled();
  });
});
