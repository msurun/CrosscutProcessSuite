// src/knowledgeProposalApi.test.ts
//
// Tests of the proposal client: the URL it builds (ids are encoded) and the pass-through result.

import { describe, expect, it, vi } from 'vitest';

vi.mock('./api', () => ({ API_PREFIX: '/api', getJson: vi.fn() }));

import { getJson } from './api';
import { fetchKnowledgeProposal } from './knowledgeProposalApi';

describe('fetchKnowledgeProposal', () => {
  it('requests the encoded proposal URL and returns the body', async () => {
    const body = { loop: 'FIC 1', proposals: {}, needs_step_test: true };
    vi.mocked(getJson).mockResolvedValue(body);
    const result = await fetchKnowledgeProposal('ds 1', 'FIC 1');
    expect(getJson).toHaveBeenCalledWith('/api/datasets/ds%201/loops/FIC%201/knowledge/proposal');
    expect(result).toEqual(body);
  });
});
