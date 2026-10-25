import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import demo from "../../../sample-data/demo-building.json";
import type { FloorMap } from "../api/types";
import FloorPlanSvg from "../components/FloorPlanSvg";
import Layout from "../components/Layout";
import Landing from "../pages/Landing";
const demoMap = demo as unknown as FloorMap;
const json = (data: unknown, status = 200) =>
  Promise.resolve(new Response(JSON.stringify(data), { status }));
afterEach(() => vi.unstubAllGlobals());
function library() {
  render(
    <MemoryRouter>
      <Routes>
        <Route path="/" element={<Landing />} />
        <Route path="/maps/:id/walk" element={<p>walkthrough opened</p>} />
      </Routes>
    </MemoryRouter>,
  );
}
describe("Space library", () => {
  it("opens the demo straight into the walkthrough", async () => {
    const fetchMock = vi.fn((url: string) =>
      url.endsWith("/api/maps")
        ? json([])
        : json({ map: { ...demoMap, id: "demo-1234" } }),
    );
    vi.stubGlobal("fetch", fetchMock);
    library();
    await userEvent.click(screen.getByRole("button", { name: /Try Demo/ }));
    expect(await screen.findByText("walkthrough opened")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/demo",
      expect.objectContaining({ method: "POST" }),
    );
  });
  it("opens saved maps directly and has no editor or print navigation", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() =>
        json([
          { id: "saved", name: "My apartment", landmarks: 4, synthetic: false },
        ]),
      ),
    );
    library();
    expect(
      await screen.findByRole("link", { name: /My apartment/ }),
    ).toHaveAttribute("href", "/maps/saved/walk");
    expect(screen.queryByText("3D preview")).not.toBeInTheDocument();
  });
  it("imports a scan directly into the walkthrough", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn((url: string) =>
        url.endsWith("/api/maps")
          ? json([])
          : json({ map: { ...demoMap, id: "scan" } }),
      ),
    );
    library();
    await userEvent.upload(
      screen.getByLabelText("Choose a file"),
      new File(["{}"], "scan.json", { type: "application/json" }),
    );
    expect(await screen.findByText("walkthrough opened")).toBeInTheDocument();
  });
  it("shows parsing details and recovers from an unreachable server", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn((url: string) =>
        url.endsWith("/api/maps")
          ? json([])
          : json(
              {
                error: {
                  message: "Invalid JSON.",
                  details: ["walls: required"],
                },
              },
              400,
            ),
      ),
    );
    library();
    await userEvent.upload(
      screen.getByLabelText("Choose a file"),
      new File(["{"], "broken.json", { type: "application/json" }),
    );
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Invalid JSON. walls: required",
    );
    vi.stubGlobal(
      "fetch",
      vi.fn(() => Promise.reject(new TypeError("Failed to fetch"))),
    );
    await userEvent.click(screen.getByRole("button", { name: /Try Demo/ }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      /Cannot reach the TouchSpace server/,
    );
  });
  it("rejects non-JSON files before uploading", async () => {
    const fetchMock = vi.fn(() => json([]));
    vi.stubGlobal("fetch", fetchMock);
    library();
    await userEvent.upload(
      screen.getByLabelText("Choose a file"),
      new File(["x"], "photo.png", { type: "image/png" }),
      { applyAccept: false },
    );
    expect(await screen.findByRole("alert")).toHaveTextContent(
      '"photo.png" is not a JSON file',
    );
    expect(fetchMock).not.toHaveBeenCalledWith("/api/scans", expect.anything());
  });
});
describe("Accessible floor plan", () => {
  it("exposes every landmark to keyboard and assistive technology", () => {
    render(
      <FloorPlanSvg
        map={demoMap}
        layers={{ rooms: true, objects: true, paths: true, landmarks: true }}
        selectedId={null}
        label="plan"
      />,
    );
    expect(screen.getAllByRole("button")).toHaveLength(
      demoMap.landmarks.length,
    );
    const entrance = screen.getByRole("button", {
      name: /Main Entrance, entrance, starting point/,
    });
    expect(entrance).toHaveAttribute("tabindex", "0");
    fireEvent.keyDown(entrance, { key: "Enter" });
  });
});
it("keeps the skip link and main landmark", async () => {
  render(
    <Layout>
      <p>content</p>
    </Layout>,
    { wrapper: MemoryRouter },
  );
  await userEvent.tab();
  expect(
    screen.getByRole("link", { name: "Skip to main content" }),
  ).toHaveFocus();
  expect(screen.getByRole("main")).toHaveAttribute("id", "main");
});
