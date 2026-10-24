import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import demo from "../../../sample-data/demo-building.json";
import type { AskResult, FloorMap } from "../api/types";
import VoiceExplorer from "../pages/VoiceExplorer";

const demoMap = { ...(demo as unknown as FloorMap), bounds: { min_x: 0, min_y: 0, max_x: 16, max_y: 10 } };
const spoken: string[] = [];

const whereAnswer: AskResult = {
  answer: "Restroom is on the north side of the map.",
  intent: "where",
  place_ids: ["lm_restroom"],
  route: null,
  context: { last_place_id: "lm_restroom", current_place_id: "lm_entrance", avoid_stairs: false },
  understood_by: "rules",
  safety_note: null,
  suggestions: ["How do I get there?"],
};

const routeAnswer: AskResult = {
  answer: "From Main Entrance to Restroom is about 12 meters. Start at Main Entrance. You'll reach Restroom.",
  intent: "route",
  place_ids: ["lm_restroom"],
  route: {
    found: true, origin_node: "n_entrance", destination_node: "n_restroom", origin_name: "Main Entrance",
    destination_name: "Restroom", node_ids: ["n_entrance", "n_restroom"],
    points: [{ x: 3.5, y: 0.6 }, { x: 7.5, y: 7.6 }], distance_m: 11.54, avoided_stairs: false, reason: null,
    spoken: "Start at Main Entrance. You'll reach Restroom.",
    steps: [
      { kind: "start", instruction: "Start at Main Entrance.", distance_m: 0, node_ids: [] },
      { kind: "arrive", instruction: "You'll reach Restroom.", distance_m: 0, node_ids: [] },
    ],
  },
  context: { last_place_id: "lm_restroom", current_place_id: "lm_entrance", avoid_stairs: false },
  understood_by: "rules",
  safety_note: "These directions follow the paths recorded on this map. Keep using your cane.",
  suggestions: [],
};

function setup(answers: AskResult[]) {
  const asked: { question: string; context: unknown }[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn((url: string, init?: RequestInit) => {
      if (url.endsWith("/api/health")) return Promise.resolve(new Response(JSON.stringify({ features: { cartesia: false } })));
      if (url.endsWith("/ask")) {
        asked.push(JSON.parse(init!.body as string));
        return Promise.resolve(new Response(JSON.stringify(answers.shift()), { status: 200 }));
      }
      if (url.includes("/api/maps/")) {
        return Promise.resolve(new Response(JSON.stringify({ map: demoMap, issues: [], model: { status: "none" }, processing_steps: [] })));
      }
      return Promise.resolve(new Response("{}", { status: 404 }));
    }),
  );
  render(
    <MemoryRouter initialEntries={["/maps/demo-1/voice"]}>
      <Routes>
        <Route path="/maps/:mapId/voice" element={<VoiceExplorer />} />
      </Routes>
    </MemoryRouter>,
  );
  return asked;
}

beforeEach(() => {
  spoken.length = 0;
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

describe("Voice Explorer", () => {
  it("answers typed questions, keeps context for follow-ups, and speaks the answer", async () => {
    const asked = setup([whereAnswer, routeAnswer]);
    const input = await screen.findByLabelText("Ask a question about this map");
    expect(screen.getByText(/not a replacement for your cane or guide dog/)).toBeInTheDocument();

    await userEvent.type(input, "Where is the restroom?{Enter}");
    expect(await screen.findByText("Restroom is on the north side of the map.")).toBeInTheDocument();
    expect(asked[0]).toEqual({
      question: "Where is the restroom?",
      context: { last_place_id: null, current_place_id: "lm_entrance", avoid_stairs: false },
    });
    expect(spoken).toEqual(["Restroom is on the north side of the map."]);

    await userEvent.click(screen.getByRole("button", { name: "How do I get there?" }));
    const directions = await screen.findByRole("list", { name: "Directions to Restroom" });
    expect(within(directions).getAllByRole("listitem").map((li) => li.textContent)).toEqual([
      "Start at Main Entrance.",
      "You'll reach Restroom.",
    ]);
    // The follow-up carries the context returned by the first answer.
    expect((asked[1].context as { last_place_id: string }).last_place_id).toBe("lm_restroom");
    // Directions are spoken with the safety note.
    expect(spoken[1]).toContain("Keep using your cane.");
  });

  it("works without speaking when the user turns speech off", async () => {
    setup([whereAnswer]);
    await userEvent.click(await screen.findByLabelText("Speak answers aloud"));
    await userEvent.type(screen.getByLabelText("Ask a question about this map"), "Where is the restroom?{Enter}");
    await screen.findByText("Restroom is on the north side of the map.");
    expect(spoken).toEqual([]);
  });

  it("sends the chosen starting point and stair preference", async () => {
    const asked = setup([whereAnswer]);
    await userEvent.selectOptions(await screen.findByLabelText("I'm starting from"), "lm_study");
    await userEvent.click(screen.getByLabelText("Avoid stairs in directions"));
    await userEvent.click(screen.getByRole("button", { name: "Where is the restroom?" }));
    await screen.findByText("Restroom is on the north side of the map.");
    expect(asked[0].context).toEqual({ last_place_id: null, current_place_id: "lm_study", avoid_stairs: true });
  });

  it("is fully usable from the keyboard", async () => {
    setup([whereAnswer]);
    const input = await screen.findByLabelText("Ask a question about this map");
    expect(input).toHaveFocus(); // the question box is ready on arrival
    await userEvent.keyboard("Where is the restroom?{Enter}");
    await screen.findByText("Restroom is on the north side of the map.");
    expect(input).toHaveFocus(); // focus returns for the next question
    // With the box empty, Ask is disabled and skipped, so Tab goes straight to the microphone.
    await userEvent.tab();
    expect(screen.getByRole("button", { name: "Speak a question" })).toHaveFocus();
  });
});
