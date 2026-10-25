import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import demo from "../../../sample-data/demo-building.json";
import type { FloorMap } from "../api/types";
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
vi.mock("../components/WalkthroughScene", () => ({
  default: () => <div data-testid="first-person-scene" />,
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
describe("Immersive walkthrough", () => {
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
