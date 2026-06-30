/**
 * Showcase API client — communicates with the showcase FastAPI endpoints.
 */

import { API_BASE } from "./sqlDemo";
import type { SingleResult, DiffResult } from "./sqlDemo";

// =========================================================================
// Types
// =========================================================================

export interface SceneListItem {
  scene_id: string;
  scene_name: string;
  type: "SQL" | "API" | "ORM";
  description: string;
  category: string;
  tags: string[];
  migration_insight: string;
  key_differences: string[];
}

export interface SceneListResponse {
  total: number;
  scenes: SceneListItem[];
}

export interface SceneResult {
  scene_id: string;
  scene_name: string;
  type: string;
  description: string;
  status: string;
  results: Record<string, SingleResult>;
  diff: DiffResult;
  diff_summary: string;
  migration_insight: string;
  key_differences: string[];
  orm_sql_generated?: Record<string, string>;
  execution_time_ms: number;
  error?: string;
}

export interface ResetResponse {
  success: boolean;
  results: Record<string, {
    success: boolean;
    tables_seeded: Record<string, number>;
    elapsed_ms: number;
    error: string | null;
  }>;
}

// =========================================================================
// API functions
// =========================================================================

export async function fetchScenes(type?: string): Promise<SceneListItem[]> {
  const url = type
    ? `${API_BASE}/api/showcase/scenes?type=${encodeURIComponent(type)}`
    : `${API_BASE}/api/showcase/scenes`;

  const res = await fetch(url);
  if (!res.ok) {
    return [];
  }
  const data: SceneListResponse = await res.json();
  return data.scenes;
}

export async function executeScene(sceneId: string): Promise<SceneResult> {
  const res = await fetch(`${API_BASE}/api/showcase/execute/${encodeURIComponent(sceneId)}`, {
    method: "POST",
  });

  if (!res.ok) {
    const text = await res.text();
    return {
      scene_id: sceneId,
      scene_name: sceneId,
      type: "",
      description: "",
      status: "error",
      results: {},
      diff: {
        row_count_diff: false,
        row_count_details: {},
        column_diff: false,
        column_details: [],
        value_diff: [],
      },
      diff_summary: `HTTP ${res.status}: ${text}`,
      migration_insight: "",
      key_differences: [],
      execution_time_ms: 0,
      error: `HTTP ${res.status}: ${text}`,
    };
  }

  return res.json();
}

export async function resetShowcase(): Promise<ResetResponse> {
  const res = await fetch(`${API_BASE}/api/showcase/reset`, {
    method: "POST",
  });

  if (!res.ok) {
    return { success: false, results: {} };
  }

  return res.json();
}
