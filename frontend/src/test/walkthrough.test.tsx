import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import demo from "../../../sample-data/demo-building.json";
import type { AskResult, FloorMap, Point2D, RouteResult } from "../api/types";
import Walkthrough from "../pages/Walkthrough";
const voice = vi.hoisted(() => ({
  start: vi.fn(),
  stop: vi.fn(),
  cancel: vi.fn(),
  speak: vi.fn(),
  callbacks: null as null | {
    onResult: (text: string) => void;
    onError: (text: string) => void;
    onStateChange: (listening: boolean) => void;
  },
  setup: null as null | Promise<void>,
}));
const padSdk = vi.hoisted(() => ({
  message: null as null | ((device: object, code: string, message: string) => void),
  key: null as null | ((device: object, code: string, message: string) => void),
  device: { numberCellColumns: 30, numberCellRows: 10, numberBrailleCellColumns: 20 },
}));
vi.mock("../dotpad/vendor/DotPadSDK-3.0.4.js", () => ({
  DataCodes: { Connected: "Connected" },
  DisplayMode: { GraphicMode: "GraphicMode", TextMode: "TextMode" },
  DotPadScanner: class {
    async startUsbScan() { return {}; }
  },
  DotPadSDK: class {
    setCallBack(message: typeof padSdk.message, key: typeof padSdk.key) {
      padSdk.message = message;
      padSdk.key = key;
    }
    async connectUsbDevice() {
      padSdk.message?.(padSdk.device, "Connected", "");
      return padSdk.device;
    }
    displayGraphicData() {}
    async displayTextData() {}
    disconnect() {}
  },
}));
vi.mock("../components/WalkthroughScene", () => ({
  default: ({ route }: { route?: Point2D[] }) => (
    <div data-testid="first-person-scene" data-route={JSON.stringify(route ?? [])} />
  ),
}));
vi.mock("../lib/voice", () => ({
  stopSpeaking: vi.fn(),
  speak: voice.speak,
  createListener: vi.fn(async (cb) => {
    voice.callbacks = cb;
    if (voice.setup) await voice.setup;
    return {
      engine: "browser",
      start: voice.start,
      stop: voice.stop,
      cancel: voice.cancel,
    };
  }),
}));
const demoMap = {
  ...(demo as unknown as FloorMap),
  bounds: { min_x: 0, min_y: 0, max_x: 16, max_y: 10 },
};
let fetchMock: ReturnType<typeof vi.fn>;
beforeEach(() => {
  vi.clearAllMocks();
  voice.setup = null;
  voice.callbacks = null;
  voice.start.mockImplementation(async () => {
    voice.callbacks?.onStateChange(true);
  });
  voice.stop.mockImplementation(async () => {
    voice.callbacks?.onStateChange(false);
    voice.callbacks?.onResult("Where is the restroom?");
  });
  voice.speak.mockResolvedValue({
    engine: "browser",
    done: Promise.resolve(),
    stop: vi.fn(),
  });
  fetchMock = vi.fn((url: string, init?: RequestInit) => {
    if (url.endsWith("/ask"))
      return Promise.resolve(
        new Response(
          JSON.stringify({
            answer: "Restroom is on the north side of the map.",
            intent: "where",
            place_ids: ["lm_restroom"],
            route: null,
            context: JSON.parse(init!.body as string).context,
            suggestions: [],
          }),
        ),
      );
    return Promise.resolve(
      new Response(
        JSON.stringify({
          map: demoMap,
          issues: [],
          model: { status: "none" },
          processing_steps: [],
        }),
      ),
    );
  });
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => vi.unstubAllGlobals());
function setup() {
  render(
    <MemoryRouter initialEntries={["/maps/demo-1/walk"]}>
      <Routes>
        <Route path="/maps/:mapId/walk" element={<Walkthrough />} />
      </Routes>
    </MemoryRouter>,
  );
}
async function area() {
  return screen.findByRole("application", { name: "Walk area" });
}
const plannedRoute: RouteResult = {
  found: true, origin_node: "start", destination_node: "end",
  origin_name: "Lobby", destination_name: "Restroom",
  node_ids: ["start", "end"],
  points: [{ x: 3.5, y: 2 }, { x: 3.5, y: 5 }, { x: 8, y: 5 }, { x: 8, y: 8 }],
  distance_m: 10.5, steps: [], avoided_stairs: false, reason: null, spoken: "Walk to the restroom.",
};
const routeAnswer = (route: RouteResult): AskResult => ({
  answer: "Planned route.", intent: "route", route,
  place_ids: [], context: { current_place_id: null, last_place_id: null, avoid_stairs: false },
  understood_by: "rules", safety_note: null, suggestions: [],
});
async function askTyped(text: string) {
  const input = screen.getByRole("textbox", { name: "Your question" });
  await userEvent.clear(input);
  await userEvent.type(input, text);
  await userEvent.click(screen.getByRole("button", { name: "Send question" }));
}
describe("Immersive walkthrough", () => {
  it("keeps routes across questions, movement and zoom, and dismisses from all views via hardware while the panel is hidden", async () => {
    vi.stubGlobal("isSecureContext", true);
    vi.stubGlobal("navigator", { serial: {} });
    setup();
    await area();
    await userEvent.click(screen.getByRole("button", { name: "DotPad" }));
    await userEvent.click(screen.getByRole("button", { name: "Connect USB" }));
    await screen.findByRole("button", { name: "Disconnect DotPad" });
    await userEvent.click(screen.getByRole("button", { name: "Type a question" }));
    fetchMock.mockResolvedValueOnce(new Response(JSON.stringify(routeAnswer(plannedRoute))));
    await askTyped("How do I get to the restroom?");
    const pad = screen.getByRole("img", { name: /^DotPad preview/ });
    expect(pad).toHaveAccessibleName(/Route to Restroom: [1-9]\d* route pins visible/);
    const scene = screen.getByTestId("first-person-scene");
    expect(scene).toHaveAttribute("data-route", JSON.stringify(plannedRoute.points));
    await askTyped("Where am I?"); // local answer clears assistant.result
    expect(pad).toHaveAccessibleName(/Route to Restroom/);
    await askTyped("Where is the restroom?"); // non-route server answer
    expect(pad).toHaveAccessibleName(/Route to Restroom/);
    fetchMock.mockRejectedValueOnce(new Error("Network unavailable"));
    await askTyped("What is near the exit?");
    expect(pad).toHaveAccessibleName(/Route to Restroom/);
    fetchMock.mockResolvedValueOnce(new Response(JSON.stringify(routeAnswer({
      ...plannedRoute, found: false, points: [], reason: "No route found",
    }))));
    await askTyped("How do I get to the stairs?");
    expect(pad).toHaveAccessibleName(/Route to Restroom/);
    await userEvent.click(screen.getByRole("button", { name: "Zoom in" }));
    fireEvent.click(screen.getByRole("button", { name: "Step forward" }));
    expect(pad).toHaveAccessibleName(/Route to Restroom/);
    expect(scene).toHaveAttribute("data-route", JSON.stringify(plannedRoute.points));

    const replacement = { ...plannedRoute, destination_name: "Exit", points: plannedRoute.points.slice(0, 3) };
    fetchMock.mockResolvedValueOnce(new Response(JSON.stringify(routeAnswer(replacement))));
    await askTyped("How do I get to the exit?");
    expect(pad).toHaveAccessibleName(/Route to Exit/);
    await userEvent.click(screen.getByRole("button", { name: "Floor plan" }));
    expect(screen.getByText("To Exit")).toBeInTheDocument();
    act(() => padSdk.key?.(padSdk.device, "KeyFunction3", "2"));
    expect(scene).toHaveAttribute("data-route", "[]");
    expect(screen.queryByText("To Exit")).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "DotPad" }));
    expect(pad).not.toHaveAccessibleName(/Route to/);
    expect(screen.getByRole("status", { name: "DotPad route" })).toHaveTextContent("No active route");
    await askTyped("Where is the restroom?");
    expect(pad).not.toHaveAccessibleName(/Route to/);
  });

  it("does not restore a dismissed route from an answer already in flight", async () => {
    vi.stubGlobal("isSecureContext", true);
    vi.stubGlobal("navigator", { serial: {} });
    setup();
    await area();
    await userEvent.click(screen.getByRole("button", { name: "DotPad" }));
    await userEvent.click(screen.getByRole("button", { name: "Connect USB" }));
    await screen.findByRole("button", { name: "Disconnect DotPad" });
    await userEvent.click(screen.getByRole("button", { name: "Type a question" }));
    fetchMock.mockResolvedValueOnce(new Response(JSON.stringify(routeAnswer(plannedRoute))));
    await askTyped("How do I get to the restroom?");
    let finish!: (response: Response) => void;
    fetchMock.mockReturnValueOnce(new Promise<Response>((resolve) => { finish = resolve; }));
    await askTyped("How do I get to the exit?");
    act(() => padSdk.key?.(padSdk.device, "KeyFunction3", "2"));
    await act(async () => { finish(new Response(JSON.stringify(routeAnswer(plannedRoute)))); });
    expect(screen.getByRole("img", { name: /^DotPad preview/ })).not.toHaveAccessibleName(/Route to/);
    // A fresh request after dismissal can highlight a route again.
    fetchMock.mockResolvedValueOnce(new Response(JSON.stringify(routeAnswer(plannedRoute))));
    await askTyped("How do I get to the restroom?");
    expect(screen.getByRole("img", { name: /^DotPad preview/ })).toHaveAccessibleName(/Route to Restroom/);
  });
  it("shares position between the first-person view, map and keyboard navigation", async () => {
    setup();
    const walk = await area();
    expect(await screen.findByTestId("first-person-scene")).toBeInTheDocument();
    expect(walk).toHaveTextContent("Lobby · facing north");
    walk.focus();
    await userEvent.keyboard("{Shift>}{ArrowRight}{/Shift}");
    expect(walk).toHaveTextContent("Lobby · facing east");
    await userEvent.keyboard("e");
    expect(
      screen.getByRole("status", { name: "Navigation" }),
    ).toHaveTextContent(/^In Lobby, facing east\./);
    expect(voice.speak).toHaveBeenLastCalledWith(
      expect.stringMatching(/^In Lobby, facing east\./),
    );
  });
  it("stops at walls and warns when walking outside the map", async () => {
    setup();
    const walk = await area();
    walk.focus();
    await userEvent.keyboard("{Shift>}{ArrowLeft}{/Shift}");
    for (let i = 0; i < 16; i++) await userEvent.keyboard("{ArrowUp}");
    expect(
      screen.getByRole("status", { name: "Navigation" }),
    ).toHaveTextContent(/^(Wall|Sofa) ahead\.$/);
    await userEvent.selectOptions(
      screen.getByLabelText("Start from"),
      "lm_entrance",
    );
    walk.focus();
    await userEvent.keyboard("t");
    for (let i = 0; i < 6; i++) await userEvent.keyboard("{ArrowUp}");
    expect(walk).toHaveTextContent("Outside the mapped area");
    await userEvent.keyboard("e");
    expect(voice.speak).toHaveBeenLastCalledWith(
      expect.stringMatching(/outside the mapped area/),
    );
  });
  it("keeps touch controls, relocates to landmarks, and updates the DotPad preview", async () => {
    setup();
    await area();
    await userEvent.click(screen.getByRole("button", { name: "DotPad" }));
    const pad = screen.getByRole("img", {
      name: /^DotPad preview, 60 by 40 pins/,
    });
    const before = pad.getAttribute("aria-label");
    fireEvent.click(screen.getByRole("button", { name: "Step forward" }));
    fireEvent.click(screen.getByRole("button", { name: "Step forward" }));
    expect(pad.getAttribute("aria-label")).not.toEqual(before);
    await userEvent.click(screen.getByRole("button", { name: "Floor plan" }));
    await userEvent.selectOptions(
      screen.getByLabelText("Start from"),
      "lm_restroom",
    );
    expect(await area()).toHaveTextContent("Restroom · facing north");
  });
  it("zooms around the user, follows movement, retains zoom across panels and restores overview", async () => {
    setup();
    await area();
    await userEvent.click(screen.getByRole("button", { name: "DotPad" }));
    const pad = screen.getByRole("img", { name: /^DotPad preview/ });
    const overview = pad.getAttribute("aria-label");
    expect(screen.getByRole("button", { name: "Zoom out" })).toBeDisabled();
    await userEvent.click(screen.getByRole("button", { name: "Zoom in" }));
    expect(screen.getByRole("status", { name: "DotPad zoom level" })).toHaveTextContent("2×");
    expect(pad).toHaveAccessibleName(/column 31, row 21/);
    fireEvent.click(screen.getByRole("button", { name: "Step forward" }));
    expect(pad).toHaveAccessibleName(/column 31, row 21/);
    await userEvent.click(screen.getByRole("button", { name: "Zoom in" }));
    expect(screen.getByRole("button", { name: "Zoom in" })).toBeDisabled();
    await userEvent.click(screen.getByRole("button", { name: "Floor plan" }));
    await userEvent.selectOptions(screen.getByLabelText("Start from"), "lm_restroom");
    await userEvent.click(screen.getByRole("button", { name: "DotPad" }));
    expect(screen.getByRole("status", { name: "DotPad zoom level" })).toHaveTextContent("4×");
    expect(pad).toHaveAccessibleName(/column 31, row 21/);
    await userEvent.click(screen.getByRole("button", { name: "Zoom out" }));
    await userEvent.click(screen.getByRole("button", { name: "Zoom out" }));
    expect(screen.getByRole("status", { name: "DotPad zoom level" })).toHaveTextContent("Overview");
    expect(pad.getAttribute("aria-label")).not.toEqual(overview);
    expect(pad).not.toHaveAccessibleName(/column 31, row 21/);
  });
  it("holds Space to listen, ignores repeats, pauses movement, and sends on release", async () => {
    setup();
    const walk = await area();
    walk.focus();
    fireEvent.keyDown(walk, { key: " ", code: "Space" });
    await waitFor(() => expect(voice.start).toHaveBeenCalledOnce());
    expect(screen.getByText("Listening · release to send")).toBeInTheDocument();
    fireEvent.keyDown(walk, { key: " ", code: "Space", repeat: true });
    fireEvent.keyDown(walk, { key: "ArrowRight" });
    expect(walk).toHaveTextContent("Lobby · facing north");
    fireEvent.keyUp(walk, { key: " ", code: "Space" });
    expect(
      await screen.findByText("Restroom is on the north side of the map."),
    ).toBeInTheDocument();
    expect(voice.stop).toHaveBeenCalledOnce();
    const call = fetchMock.mock.calls.find(([url]) => url.endsWith("/ask"));
    expect(JSON.parse(call![1].body)).toMatchObject({
      question: "Where is the restroom?",
      context: { current_place_id: "lm_entrance" },
    });
  });
  it("does not start recording if Space is released while voice setup is pending", async () => {
    let finish!: () => void;
    voice.setup = new Promise<void>((resolve) => {
      finish = resolve;
    });
    setup();
    const walk = await area();
    fireEvent.keyDown(walk, { key: " ", code: "Space" });
    fireEvent.keyUp(walk, { key: " ", code: "Space" });
    finish();
    await waitFor(() => expect(voice.cancel).toHaveBeenCalled());
    expect(voice.start).not.toHaveBeenCalled();
  });
  it("provides typed questions without stealing Space from the input", async () => {
    setup();
    await area();
    await userEvent.click(
      screen.getByRole("button", { name: "Type a question" }),
    );
    await userEvent.type(
      screen.getByRole("textbox", { name: "Your question" }),
      "Where am I?",
    );
    expect(voice.start).not.toHaveBeenCalled();
    await userEvent.click(
      screen.getByRole("button", { name: "Send question" }),
    );
    expect(
      await screen.findByText(/^In Lobby, facing north\./),
    ).toBeInTheDocument();
    expect(fetchMock.mock.calls.some(([url]) => url.endsWith("/ask"))).toBe(
      false,
    );
  });
  it("cancels microphone capture on focus loss", async () => {
    setup();
    const walk = await area();
    fireEvent.keyDown(walk, { key: " ", code: "Space" });
    await waitFor(() => expect(voice.start).toHaveBeenCalled());
    fireEvent.blur(window);
    expect(voice.cancel).toHaveBeenCalled();
    expect(
      screen.getByText("Hold Space to ask anything about this space"),
    ).toBeInTheDocument();
  });
});
