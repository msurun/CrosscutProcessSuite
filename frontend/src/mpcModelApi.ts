// Typed client for immutable identified-model versions.
// Every edit names the verified parent hash and carries its audit explanation.
import { apiFetch } from "./http";

export interface ModelPairValues {
  input_name: string; cv_name: string; gain: number;
  time_constant_s: number; dead_time_s: number; enabled: boolean;
}
export interface ModelPair extends ModelPairValues {
  quality: { passed: boolean; reasons: string[]; free_run_r2: number | null; excitation_events: number };
}
export interface IdentModelVersion {
  model_id: string; sha256: string; input_names: string[]; cv_names: string[];
  cycle_s: number; pairs: ModelPair[]; parent_model_id?: string | null;
  parent_sha256?: string | null; author?: string | null; reason?: string | null;
}
export interface ModelEdit {
  parent_sha256: string; author: string; reason: string; pairs: ModelPairValues[];
}

/** Decode a model response and preserve server validation and integrity explanations. */
async function readModel(response: Response): Promise<IdentModelVersion> {
  const body = await response.json();
  if (!response.ok) throw new Error(typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail));
  return body as IdentModelVersion;
}

/** Read one verified artifact without changing it. */
export async function loadMpcModel(modelId: string): Promise<IdentModelVersion> {
  return readModel(await apiFetch(`/api/mpc/models/${encodeURIComponent(modelId)}`));
}

/** Save a complete edited matrix as a fresh artifact, preserving the parent. */
export async function saveMpcModel(modelId: string, edit: ModelEdit): Promise<IdentModelVersion> {
  return readModel(await apiFetch(`/api/mpc/models/${encodeURIComponent(modelId)}/versions`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(edit),
  }));
}
