import { bridgeUrl, poseMessage } from "./dotpadLink";

describe("dotpad link", () => {
  it("is off without ?dotpad", () => {
    expect(bridgeUrl("?x=1", "192.168.1.5")).toBeNull();
  });
  it("goes through the page's own /bridge proxy when given a token", () => {
    expect(bridgeUrl("?dotpad=ab12", "192.168.1.5:5173")).toBe("ws://192.168.1.5:5173/bridge/phone?token=ab12");
    expect(bridgeUrl("?dotpad=ab12", "x.ngrok-free.app", "https:")).toBe("wss://x.ngrok-free.app/bridge/phone?token=ab12");
  });
  it("accepts a full ws:// address", () => {
    expect(bridgeUrl("?dotpad=ws://10.0.0.2:8765/phone?token=zz", "x")).toBe("ws://10.0.0.2:8765/phone?token=zz");
  });
  it("sends heading in radians, clockwise from map-up", () => {
    const m = JSON.parse(poseMessage({ position: { x: 1, y: 2 }, heading: 90 }));
    expect(m).toMatchObject({ type: "pose", frame: "plan", x: 1, y: 2 });
    expect(m.heading).toBeCloseTo(Math.PI / 2);
  });
});
