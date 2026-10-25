// Mirrors backend/app/models. Keep in sync with the Pydantic schema.

export interface Point2D {
  x: number;
  y: number;
}

export interface Bounds {
  min_x: number;
  min_y: number;
  max_x: number;
  max_y: number;
}

export type Confidence = "low" | "medium" | "high" | null;

export interface Wall {
  id: string;
  start: Point2D;
  end: Point2D;
  thickness: number;
  height?: number | null;
  confidence?: Confidence;
  metadata?: Record<string, unknown>;
}

export interface WallGap {
  id: string;
  position: Point2D;
  width: number;
  wall_id: string | null;
  confidence?: Confidence;
  metadata?: Record<string, unknown>;
}

export interface Door extends WallGap {
  kind: "door";
  is_open?: boolean | null;
}
export interface Opening extends WallGap {
  kind: "opening";
}
export interface Window extends WallGap {
  kind: "window";
}

export interface MapObject {
  id: string;
  category: string;
  position: Point2D;
  width: number;
  depth: number;
  height?: number | null;
  rotation: number;
  label: string | null;
  confidence?: Confidence;
  include_in_tactile: boolean;
  hidden: boolean;
  metadata?: Record<string, unknown>;
}

export const LANDMARK_TYPES = [
  "entrance",
  "exit",
  "restroom",
  "stairs",
  "elevator",
  "information",
  "room",
  "hallway",
  "other",
] as const;
export type LandmarkType = (typeof LANDMARK_TYPES)[number];

export interface Landmark {
  id: string;
  name: string;
  type: LandmarkType;
  position: Point2D;
  description: string;
  show_on_tactile: boolean;
  nav_node_id: string | null;
  source: "manual" | "detected" | "synthetic";
}

export interface Room {
  id: string;
  name: string;
  polygon: Point2D[];
  description: string;
}

export interface NavNode {
  id: string;
  position: Point2D;
  label: string | null;
  kind: "place" | "door" | "junction";
  landmark_id: string | null;
  room_id: string | null;
}

export interface NavEdge {
  id: string;
  a: string;
  b: string;
  traversable: boolean;
  accessibility: "unknown" | "step_free" | "has_steps";
  source: "manual" | "synthetic" | "derived";
  notes: string;
}

export interface TactileSettings {
  max_width_mm: number;
  max_depth_mm: number;
  margin_mm: number;
  base_thickness_mm: number;
  wall_height_mm: number;
  wall_width_mm: number;
  min_door_gap_mm: number;
  landmark_size_mm: number;
  landmark_height_mm: number;
  object_height_mm: number;
  path_dot_diameter_mm: number;
  path_dot_height_mm: number;
  path_dot_spacing_mm: number;
  include_landmarks: boolean;
  include_objects: boolean;
  include_paths: boolean;
  include_legend: boolean;
  orientation_marker: boolean;
}

export interface FloorMap {
  schema_version: string;
  id: string;
  name: string;
  units: "meters";
  source: { kind: "synthetic" | "roomplan" | "manual"; description: string; importer_version?: string | null; captured_at?: string | null };
  floor_level: number | null;
  bounds: Bounds | null;
  walls: Wall[];
  doors: Door[];
  openings: Opening[];
  windows: Window[];
  objects: MapObject[];
  rooms: Room[];
  landmarks: Landmark[];
  navigation: { nodes: NavNode[]; edges: NavEdge[] };
  start_landmark_id: string | null;
  tactile: TactileSettings;
  created_at: string | null;
  updated_at: string | null;
}

export interface ValidationIssue {
  severity: "error" | "warning" | "info";
  code: string;
  message: string;
  element_id: string | null;
}

export interface MeshCheck {
  name: string;
  passed: boolean;
  detail: string;
}

export interface TactileFeature {
  kind: string;
  label: string;
  element_id: string | null;
  symbol: string | null;
  center_mm: [number, number] | null;
  size_mm: [number, number] | null;
  height_mm: number | null;
  displaced_mm: number;
  note: string;
}

export interface TactileReport {
  map_id: string;
  width_mm: number;
  depth_mm: number;
  height_mm: number;
  scale_mm_per_m: number;
  scale_ratio: string;
  triangle_count: number;
  volume_mm3: number;
  watertight: boolean;
  body_count: number;
  checks: MeshCheck[];
  features: TactileFeature[];
  warnings: string[];
  summary: string[];
  settings: TactileSettings;
}

export interface ModelStatus {
  status: "none" | "ready" | "stale";
  generated_at: string | null;
  filename: string | null;
  report: TactileReport | null;
}

export interface MapResponse {
  map: FloorMap;
  issues: ValidationIssue[];
  model: ModelStatus;
  processing_steps: string[];
}

export interface MapSummary {
  id: string;
  name: string;
  synthetic: boolean;
  updated_at: string | null;
  walls: number;
  landmarks: number;
  model_status: ModelStatus["status"];
}

export interface RouteStep {
  kind: "start" | "walk" | "arrive";
  instruction: string;
  distance_m: number;
  node_ids: string[];
}

export interface RouteResult {
  found: boolean;
  origin_node: string;
  destination_node: string;
  origin_name: string;
  destination_name: string;
  node_ids: string[];
  points: Point2D[];
  distance_m: number;
  steps: RouteStep[];
  avoided_stairs: boolean;
  reason: string | null;
  spoken: string;
  safety_note?: string | null;
}

export interface AskContext {
  last_place_id: string | null;
  current_place_id: string | null;
  avoid_stairs: boolean;
}

export type AskIntent = "help" | "overview" | "list" | "where" | "nearby" | "route" | "whereami" | "describe" | "clarify" | "unknown";

export interface AskResult {
  answer: string;
  intent: AskIntent;
  place_ids: string[];
  route: RouteResult | null;
  context: AskContext;
  understood_by: "rules" | "claude";
  safety_note: string | null;
  suggestions: string[];
}
