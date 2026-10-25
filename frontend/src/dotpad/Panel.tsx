import { useEffect, useRef, useState } from "react";
import {
  DotPadConnection,
  supportedTransports,
  type DeviceState,
  type ZoomAction,
} from "./device";
import type { PinGrid } from "./pins";
import { knownDotPads, type KnownDotPad } from "./discovery";
import Preview from "./Preview";

export default function DotPadPanel(props: {
  grid: PinGrid;
  walker: { col: number; row: number } | null;
  text: string;
  metersPerPin: number;
  zoom: number;
  onZoom: (action: ZoomAction) => void;
}) {
  const connection = useRef<DotPadConnection | null>(null);
  const onZoom = useRef(props.onZoom);
  onZoom.current = props.onZoom;
  const [state, setState] = useState<DeviceState>("disconnected");
  const [error, setError] = useState("");
  const [knownDevices, setKnownDevices] = useState<KnownDotPad[]>([]);
  useEffect(() => {
    let active = true;
    const refreshKnownDevices = () => {
      void knownDotPads()
        .then((devices) => {
          if (active) setKnownDevices(devices);
        })
        .catch(() => {});
    };
    refreshKnownDevices();
    const device = new DotPadConnection((next, message) => {
      setState(next);
      setError(message ?? "");
      if (next !== "connecting") refreshKnownDevices();
    }, (action) => onZoom.current(action));
    connection.current = device;
    const refreshOnFocus = () => refreshKnownDevices();
    window.addEventListener("focus", refreshOnFocus);
    return () => {
      active = false;
      window.removeEventListener("focus", refreshOnFocus);
      device.dispose();
      connection.current = null;
    };
  }, []);
  useEffect(() => {
    connection.current?.update(props.grid, props.text);
  }, [props.grid, props.text]);
  const transports = supportedTransports();
  return (
    <div className="space-y-4">
      <p className="text-sm text-muted">
        Walls are raised, doors are gaps, and your position is an X.
        Zoom in to keep your position centered as you walk. On the DotPad,
        function button 1 zooms out and function button 2 zooms in.
      </p>
      <div className="flex flex-wrap items-center gap-2" role="group" aria-label="DotPad zoom">
        <button
          className="btn-secondary"
          disabled={props.zoom === 1}
          onClick={() => props.onZoom("out")}
        >
          Zoom out
        </button>
        <span role="status" aria-label="DotPad zoom level">
          {props.zoom === 1 ? "Overview" : `${props.zoom}× · centered on you`}
        </span>
        <button
          className="btn-secondary"
          disabled={props.zoom === 4}
          onClick={() => props.onZoom("in")}
        >
          Zoom in
        </button>
      </div>
      <div className="flex flex-wrap gap-2">
        {state === "connected" ? (
          <>
            <button
              className="btn-secondary"
              onClick={() => connection.current?.disconnect()}
            >
              Disconnect DotPad
            </button>
            <button
              className="btn-secondary"
              onClick={() => connection.current?.clear()}
            >
              Lower all pins
            </button>
          </>
        ) : (
          <>
            {knownDevices.map((device) => (
              <button
                key={device.id}
                className="btn-primary"
                disabled={
                  state === "connecting" || !transports.includes("bluetooth")
                }
                onClick={() =>
                  void connection.current?.reconnectBluetooth(device)
                }
              >
                Reconnect {device.name ?? "DotPad"}
              </button>
            ))}
            <button
              className="btn-primary"
              disabled={
                state === "connecting" || !transports.includes("bluetooth")
              }
              onClick={() => void connection.current?.connect("bluetooth")}
            >
              Connect Bluetooth
            </button>
            <button
              className="btn-secondary"
              disabled={
                state === "connecting" || !transports.includes("bluetooth")
              }
              onClick={() =>
                void connection.current?.connect("bluetooth", "all")
              }
            >
              Show all Bluetooth devices
            </button>
            <button
              className="btn-secondary"
              disabled={state === "connecting" || !transports.includes("usb")}
              onClick={() => void connection.current?.connect("usb")}
            >
              Connect USB
            </button>
          </>
        )}
      </div>
      <p aria-live="polite" className="text-sm">
        {state === "connected"
          ? "DotPad connected · map updates as you walk"
          : state === "connecting"
            ? "Connecting to DotPad…"
            : "DotPad disconnected · preview available"}
      </p>
      {state === "disconnected" && transports.includes("bluetooth") && (
        <p className="text-sm text-muted">
          If your DotPad disappears after the first scan, use Reconnect above
          for a device already authorized on this site. Otherwise restart the
          DotPad to restore advertising, then select it once in this site's
          picker. Disconnect it in the SDK demo before connecting here. “Show
          all Bluetooth devices” also finds devices without a DotPad name;
          select your DotPad there. Bluetooth permissions are separate for each
          site and port.
        </p>
      )}
      {!transports.length && (
        <p className="text-sm text-muted">
          Hardware connection needs Chrome with HTTPS or localhost.
        </p>
      )}
      {error && (
        <p role="alert" className="text-danger">
          {error}
        </p>
      )}
      <Preview {...props} />
    </div>
  );
}
