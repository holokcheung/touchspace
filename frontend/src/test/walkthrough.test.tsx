import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import demo from "../../../sample-data/demo-building.json";
import type { FloorMap } from "../api/types";
import Walkthrough from "../pages/Walkthrough";

const demoMap = { ...(demo as unknown as FloorMap), bounds: { min_x: 0, min_y: 0, max_x: 16, max_y: 10 } };
const spoken: string[] = [];

beforeEach(() => {
  spoken.length = 0;
  vi.stubGlobal(
    "fetch",
    vi.fn((url: string) => {
      if (url.endsWith("/api/health")) return Promise.resolve(new Response(JSON.stringify({ features: { cartesia: false } })));
      if (url.includes("/api/maps/")) {
        return Promise.resolve(new Response(JSON.stringify({ map: demoMap, issues: [], model: { status: "none" }, processing_steps: [] })));
      }
      return Promise.resolve(new Response("{}", { status: 404 }));
    }),
  );
  vi.stubGlobal(
    "SpeechSynthesisUtterance",
    class {
      onend: (() => void) | null = null;
      onerror: (() => void) | null = null;
      constructor(public text: string) {}
    },
  );
  vi.stubGlobal("speechSynthesis", { cancel: vi.fn(), speak: (u: { text: string }) => spoken.push(u.text) });
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

describe("Walk-through", () => {
  it("starts at the map's starting point and walks with the keyboard", async () => {
    setup();
    const area = await screen.findByRole("application", { name: "Walk area" });
    expect(screen.getByText(/simulated from the map, not live sensing/)).toBeInTheDocument();
    expect(area).toHaveTextContent("Lobby · facing north");

    area.focus();
    await userEvent.keyboard("{Shift>}{ArrowRight}{/Shift}");
    expect(area).toHaveTextContent("facing east");
    expect(screen.getByRole("status")).toHaveTextContent("Facing east.");

    await userEvent.keyboard(" ");
    expect(screen.getByRole("status")).toHaveTextContent(/^In Lobby, facing east\./);
    expect(spoken.at(-1)).toMatch(/^In Lobby, facing east\./);
  });

  it("bumps into walls instead of walking through them", async () => {
    setup();
    const area = await screen.findByRole("application", { name: "Walk area" });
    area.focus();
    await userEvent.keyboard("{Shift>}{ArrowLeft}{/Shift}"); // face west, toward the outside wall
    for (let i = 0; i < 16; i++) await userEvent.keyboard("{ArrowUp}");
    // A wall or the lobby sofa, whichever comes first.
    expect(screen.getByRole("status")).toHaveTextContent(/^(Wall|Sofa) ahead\.$/);
    expect(area).toHaveTextContent("Lobby");
  });

  it("says when you leave the map, so quiet never means open space", async () => {
    setup();
    const area = await screen.findByRole("application", { name: "Walk area" });
    area.focus();
    await userEvent.keyboard("t"); // face south, out through the main entrance
    for (let i = 0; i < 6; i++) await userEvent.keyboard("{ArrowUp}");
    expect(area).toHaveTextContent("Outside the mapped area");
    await userEvent.keyboard(" ");
    expect(spoken.at(-1)).toMatch(/outside the mapped area/);
  });

  it("has touch buttons that work with a single press", async () => {
    setup();
    const forward = await screen.findByRole("button", { name: "Step forward" });
    const area = screen.getByRole("application", { name: "Walk area" });
    const before = area.textContent;
    fireEvent.click(forward);
    fireEvent.click(forward);
    fireEvent.click(forward);
    expect(area.textContent).not.toBe(before);
    fireEvent.click(screen.getByRole("button", { name: "What's around me?" }));
    expect(screen.getByRole("status")).toHaveTextContent(/facing north/);
  });

  it("offers every landmark as a starting point", async () => {
    setup();
    const select = await screen.findByLabelText("Start from");
    await userEvent.selectOptions(select, "Restroom");
    expect(screen.getByRole("application", { name: "Walk area" })).toHaveTextContent("Restroom · facing north");
  });
});
