import type { AskContext, AskResult, MapResponse, MapSummary } from "./types";

const BASE = import.meta.env.VITE_API_BASE ?? "";

export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
    public code: string,
    public details: string[] = [],
  ) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${BASE}${path}`, init);
  } catch {
    throw new ApiError(
      "Cannot reach the TouchSpace server. Is the backend running on port 8000?",
      0,
      "network",
    );
  }
  if (res.ok) return (await res.json()) as T;

  let message = `Request failed (${res.status}).`;
  let code = "http_error";
  let details: string[] = [];
  try {
    const body = await res.json();
    if (body?.error) {
      message = body.error.message ?? message;
      code = body.error.code ?? code;
      const d = body.error.details;
      if (Array.isArray(d))
        details = d.map((x) =>
          typeof x === "string" ? x : (x?.detail ?? JSON.stringify(x)),
        );
    }
  } catch {
    /* non-JSON error body */
  }
  throw new ApiError(message, res.status, code, details);
}

const json = (method: string, body?: unknown): RequestInit => ({
  method,
  headers: { "Content-Type": "application/json" },
  body: body === undefined ? undefined : JSON.stringify(body),
});

export const api = {
  health: () =>
    request<{
      status: string;
      features: { gemini: boolean; cartesia: boolean };
    }>("/api/health"),
  listMaps: () => request<MapSummary[]>("/api/maps"),
  createDemo: () => request<MapResponse>("/api/demo", { method: "POST" }),
  createRoomPlanSample: () =>
    request<MapResponse>("/api/samples/roomplan", { method: "POST" }),
  createPalaceSample: () =>
    request<MapResponse>("/api/samples/palace-of-fine-arts", { method: "POST" }),
  uploadScan: (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<MapResponse>("/api/scans", { method: "POST", body: form });
  },
  getMap: (id: string) =>
    request<MapResponse>(`/api/maps/${encodeURIComponent(id)}`),
  ask: (id: string, question: string, context: AskContext) =>
    request<AskResult>(
      `/api/maps/${encodeURIComponent(id)}/ask`,
      json("POST", { question, context }),
    ),
};
