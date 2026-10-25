/**
 * Optional link from the walk-through to the live DotPad bridge (`python -m app.live`, see
 * docs/live-dotpad.md). Turned on by the page URL: `?dotpad=<token>` connects through the dev
 * server's `/bridge` proxy (same address and port as the page), or
 * `?dotpad=ws://host:8765/phone?token=...` names the bridge in full.
 * This lets a phone browser walk the map while the Mac drives the DotPad, since phone browsers
 * cannot reach the DotPad themselves (no Web Bluetooth/Serial on iOS).
 */
import { useEffect, useRef, useState } from "react";
import type { FloorMap } from "../api/types";
import type { Pose } from "./soundscape";

export function bridgeUrl(search: string, host: string, protocol = "http:"): string | null {
  const value = new URLSearchParams(search).get("dotpad");
  if (!value) return null;
  if (/^wss?:\/\//.test(value)) return value;
  return `${protocol === "https:" ? "wss" : "ws"}://${host}/bridge/phone?token=${encodeURIComponent(value)}`;
}

/** Bridge message for a walk-through pose: plan meters, heading in radians clockwise from map-up. */
export function poseMessage(pose: Pose): string {
  return JSON.stringify({
    type: "pose",
    frame: "plan",
    x: pose.position.x,
    y: pose.position.y,
    heading: (pose.heading * Math.PI) / 180,
  });
}

export function mapMessage(map: FloorMap): string {
  return JSON.stringify({ type: "map", floormap: map, name: map.name });
}

/** Keeps the bridge showing this map and pose. Returns a status line, or null when the link is off. */
export function useDotPadLink(map: FloorMap, pose: Pose | null): string | null {
  const [url] = useState(() => (typeof window === "undefined" ? null : bridgeUrl(window.location.search, window.location.host, window.location.protocol)));
  const [status, setStatus] = useState<string | null>(url ? "DotPad: connecting to the Mac…" : null);
  const ws = useRef<WebSocket | null>(null);
  const latest = useRef({ map, pose });
  latest.current = { map, pose };

  useEffect(() => {
    if (!url) return;
    let closed = false;
    let retry: ReturnType<typeof setTimeout> | undefined;
    const open = () => {
      const sock = new WebSocket(url);
      ws.current = sock;
      sock.onopen = () => {
        sock.send(JSON.stringify({ type: "hello", client: "TouchSpace web walk-through" }));
        sock.send(mapMessage(latest.current.map));
        if (latest.current.pose) sock.send(poseMessage(latest.current.pose));
      };
      sock.onmessage = (e) => {
        try {
          const msg = JSON.parse(String(e.data));
          if (msg.type === "status") {
            setStatus(msg.dotpad === "connected" ? "DotPad: connected, showing this walk" : "DotPad: Mac connected, DotPad not paired yet");
          } else if (msg.type === "error") {
            setStatus(`DotPad: the Mac could not use a message (${msg.message})`);
          }
        } catch {
          /* ignore non-JSON */
        }
      };
      sock.onclose = () => {
        if (closed) return;
        setStatus("DotPad: not connected to the Mac, retrying…");
        retry = setTimeout(open, 2000);
      };
    };
    open();
    return () => {
      closed = true;
      clearTimeout(retry);
      ws.current?.close();
    };
  }, [url]);

  useEffect(() => {
    if (ws.current?.readyState === WebSocket.OPEN) ws.current.send(mapMessage(map));
  }, [map]);

  useEffect(() => {
    if (pose && ws.current?.readyState === WebSocket.OPEN) ws.current.send(poseMessage(pose));
  }, [pose]);

  return status;
}
