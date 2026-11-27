// src/modeProposalApi.ts
//
// Client for "propose operating modes and equipment groups from history" (#145): the backend
// suggests conditions and equipment members with evidence; nothing is saved by this call.

import { API_PREFIX, getJson } from './api';

/** How sure the backend is about one proposal. */
export type ProposalConfidence = 'high' | 'medium' | 'low';

/** One condition clause of a mode: `tag op value`. */
export interface ModeClause {
  tag: string;
  op: '<' | '<=' | '>' | '>=' | '==' | '!=';
  value: number;
}

/** Why the backend proposes something: share of time, thresholds, example windows (seconds since start). */
export interface ModeEvidence {
  kind: string;
  share: number;
  thresholds: Record<string, number | string | number[]>;
  windows: [number, number][];
  events: number;
  detail: string;
}

/** A mode as the site catalogue stores it. */
export interface ModeEntry {
  id: string;
  name: string;
  scope: string;
  condition: { match: 'all' | 'any'; clauses: ModeClause[] };
}

/** An equipment entry as the site catalogue stores it (the parent is added on accept). */
export interface EquipmentEntry {
  id: string;
  name: string;
  level: 'equipment';
  tags: string[];
}

/** A proposed mode; `scope_new` means its equipment is itself a proposal that must be accepted with it. */
export interface ModeProposal {
  id: string;
  entry: ModeEntry;
  confidence: ProposalConfidence;
  evidence: ModeEvidence;
  scope_new?: boolean;
}

/** A proposed equipment group. */
export interface EquipmentProposal {
  id: string;
  entry: EquipmentEntry;
  confidence: ProposalConfidence;
  evidence: ModeEvidence;
}

/** Response of the proposal route. */
export interface ModeProposalResponse {
  dataset: string;
  modes: ModeProposal[];
  equipment: EquipmentProposal[];
}

/**
 * Ask the backend for mode and equipment proposals from one dataset's history.
 * @throws {ApiError} On a non-2xx response.
 */
export async function fetchModeProposals(datasetId: string): Promise<ModeProposalResponse> {
  const path = `datasets/${encodeURIComponent(datasetId)}/catalogue/proposals/modes`;
  return getJson<ModeProposalResponse>(`${API_PREFIX}/${path}`);
}
