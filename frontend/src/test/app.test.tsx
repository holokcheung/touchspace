import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import demo from "../../../sample-data/demo-building.json";
import type { FloorMap } from "../api/types";
import FloorPlanSvg from "../components/FloorPlanSvg";
import Layout from "../components/Layout";
import Landing from "../pages/Landing";
import Upload from "../pages/Upload";

const demoMap = demo as unknown as FloorMap;

function mockFetch(handler: (url: string, init?: RequestInit) => Response | Promise<Response>) {
  const fn = vi.fn((input: RequestInfo | URL, init?: RequestInit) => Promise.resolve(handler(String(input), init)));
  vi.stubGlobal("fetch", fn);
  return fn;
}

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("Landing", () => {
  it("shows the product name, tagline and both actions", () => {
    render(<Landing />, { wrapper: MemoryRouter });
    expect(screen.getByRole("heading", { level: 1, name: "TouchSpace AI" })).toBeInTheDocument();
    expect(screen.getByText("Scan a Space. Feel the Layout. Explore with Confidence.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Get Started" })).toHaveAttribute("href", "/upload");
    expect(screen.getByRole("button", { name: "Try Demo" })).toBeEnabled();
  });

  it("Try Demo creates a demo map and opens the editor", async () => {
    const fetchMock = mockFetch(() => json({ map: { ...demoMap, id: "demo-1234" }, issues: [], model: { status: "none" }, processing_steps: [] }, 201));
    render(
      <MemoryRouter initialEntries={["/"]}>
        <Routes>
          <Route path="/" element={<Landing />} />
          <Route path="/maps/:mapId/edit" element={<p>editor page</p>} />
        </Routes>
      </MemoryRouter>,
    );
    await userEvent.click(screen.getByRole("button", { name: "Try Demo" }));
    expect(await screen.findByText("editor page")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith("/api/demo", expect.objectContaining({ method: "POST" }));
  });

  it("explains when the backend is unreachable", async () => {
    vi.stubGlobal("fetch", vi.fn(() => Promise.reject(new TypeError("Failed to fetch"))));
    render(<Landing />, { wrapper: MemoryRouter });
    await userEvent.click(screen.getByRole("button", { name: "Try Demo" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/Cannot reach the TouchSpace server/);
  });
});

describe("Upload", () => {
  it("shows the server's parsing error and details", async () => {
    mockFetch((url) =>
      url.endsWith("/api/scans")
        ? json({ error: { code: "invalid_json", message: "The file is not valid JSON (line 1, column 12).", details: ["walls: required"] } }, 400)
        : json([]),
    );
    render(<Upload />, { wrapper: MemoryRouter });
    const input = screen.getByLabelText("Choose a file");
    await userEvent.upload(input, new File(['{"walls": ['], "broken.json", { type: "application/json" }));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("The file is not valid JSON (line 1, column 12).");
    expect(alert).toHaveTextContent("walls: required");
  });

  it("rejects non-JSON files before uploading", async () => {
    const fetchMock = mockFetch(() => json([]));
    render(<Upload />, { wrapper: MemoryRouter });
    await userEvent.upload(screen.getByLabelText("Choose a file"), new File(["x"], "photo.png", { type: "image/png" }), {
      applyAccept: false,
    });
    expect(await screen.findByRole("alert")).toHaveTextContent('"photo.png" is not a JSON file');
    expect(fetchMock).not.toHaveBeenCalledWith("/api/scans", expect.anything());
  });
});

describe("FloorPlanSvg", () => {
  const layers = { rooms: true, objects: true, paths: true, landmarks: true };

  it("exposes every landmark as a keyboard-focusable button", () => {
    render(<FloorPlanSvg map={demoMap} layers={layers} selectedId={null} label="plan" />);
    const buttons = screen.getAllByRole("button");
    expect(buttons).toHaveLength(demoMap.landmarks.length);
    expect(screen.getByRole("button", { name: /Main Entrance, entrance, starting point/ })).toHaveAttribute("tabindex", "0");
  });

  it("moves the focused landmark with arrow keys", () => {
    const onMove = vi.fn();
    const onSelect = vi.fn();
    render(<FloorPlanSvg map={demoMap} layers={layers} selectedId={null} onSelect={onSelect} onMoveLandmark={onMove} label="plan" />);
    const restroom = screen.getByRole("button", { name: /^Restroom, restroom/ });
    fireEvent.keyDown(restroom, { key: "ArrowRight" });
    fireEvent.keyDown(restroom, { key: "ArrowUp", shiftKey: true });
    expect(onMove).toHaveBeenNthCalledWith(1, "lm_restroom", { x: 7.6, y: 7.6 });
    expect(onMove).toHaveBeenNthCalledWith(2, "lm_restroom", { x: 7.5, y: 8.1 });
    expect(onSelect).toHaveBeenCalledWith("lm_restroom");
  });
});

describe("Layout", () => {
  it("provides a skip link to the main content", async () => {
    render(
      <Layout>
        <p>content</p>
      </Layout>,
      { wrapper: MemoryRouter },
    );
    await userEvent.tab();
    const skip = screen.getByRole("link", { name: "Skip to main content" });
    expect(skip).toHaveFocus();
    expect(skip).toHaveAttribute("href", "#main");
    expect(screen.getByRole("main")).toHaveAttribute("id", "main");
  });
});
