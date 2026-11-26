// src/knowledgeProposalApi.ts
//
// Client for the "propose knowledge from history" route: values the backend suggests for a
// loop (dead time, ultimate period, ...) with the evidence behind each. Nothing is saved here.

import { API_PREFIX, getJson } from './api';

/** How sure the backend is about one proposed value. */
export type ProposalConfidence = 'high' | 'medium' | 'low';

/** Where a proposal comes from: the kind of evidence, its time window (epoch seconds) and a note. */
export interface ProposalEvidence {
  kind: string;
  window: [number, number] | null;
  events: number;
  detail: string;
}

/** One proposed value; `value` is null when history gave nothing to propose. */
export interface KnowledgeProposal {
  value: number | string | null;
  evidence: ProposalEvidence;
  confidence: ProposalConfidence;
}

/** Response of the proposal route. */
export interface KnowledgeProposalResponse {
  loop: string;
  proposals: Record<string, KnowledgeProposal>;
  needs_step_test: boolean;
}

/**
 * Ask the backend to propose knowledge values for one loop from its history.
 * @throws {ApiError} On a non-2xx response.
 */
export async function fetchKnowledgeProposal(
  datasetId: string,
  loopName: string,
): Promise<KnowledgeProposalResponse> {
  const path = `datasets/${encodeURIComponent(datasetId)}/loops/${encodeURIComponent(loopName)}`;
  return getJson<KnowledgeProposalResponse>(`${API_PREFIX}/${path}/knowledge/proposal`);
}
