// frontend/src/components/KnowledgeProposals.test.tsx
// Tests for the "Propose from history" bar and proposal rows: fetch, accept, bulk accept, confirm and errors.
import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { fetchKnowledgeProposal } from "../knowledgeProposalApi";
import type { KnowledgeProposalResponse } from "../knowledgeProposalApi";
import type { KnowledgeDraft } from "./knowledgeDraft";
import {
  acceptAllHighPatch,
  FieldProposal,
  OtherProposals,
  ProposalBar,
  useProposal,
} from "./KnowledgeProposals";

vi.mock("../knowledgeProposalApi", () => ({ fetchKnowledgeProposal: vi.fn() }));

const t = (key: string, vars?: Record<string, string | number>) => (vars ? `${key} ${JSON.stringify(vars)}` : key);

const response: KnowledgeProposalResponse = {
  loop: "L1",
  needs_step_test: false,
  proposals: {
    delay_s: {
      value: 12.5,
      confidence: "high",
      evidence: { kind: "step", window: null, events: 3, detail: "from steps" },
    },
    amplitude_limit: {
      value: 5,
      confidence: "high",
      evidence: { kind: "osc", window: [0, 60], events: 1, detail: "oscillation" },
    },
    process_kind: {
      value: "self_regulating",
      confidence: "high",
      evidence: { kind: "step", window: null, events: 2, detail: "settles" },
    },
    ultimate_period_s: {
      value: 40,
      confidence: "medium",
      evidence: { kind: "osc", window: null, events: 1, detail: "period" },
    },
  },
};

interface HarnessProps {
  onAccept: (patch: Partial<KnowledgeDraft>) => void;
  onOpenSteps?: () => void;
}

/** Wires the hook to the bar and the rows, as KnowledgeEditor does. */
function Harness({ onAccept, onOpenSteps }: HarnessProps) {
  const { state, load } = useProposal("ds", "L1");
  const ready = state.status === "ready" ? state.response : null;
  return (
    <>
      <ProposalBar
        state={state}
        t={t}
        onLoad={load}
        onAcceptHigh={() => onAccept(acceptAllHighPatch(ready?.proposals ?? {}))}
        onOpenSteps={onOpenSteps}
      />
      <FieldProposal name="delay_s" response={ready} t={t} onAccept={onAccept} />
      <FieldProposal name="amplitude_limit" response={ready} t={t} onAccept={onAccept} />
      <FieldProposal name="process_kind" response={ready} t={t} onAccept={onAccept} />
      <FieldProposal name="ultimate_period_s" response={ready} t={t} onAccept={onAccept} />
      <OtherProposals response={ready} t={t} onAccept={onAccept} />
    </>
  );
}

const fetchMock = vi.mocked(fetchKnowledgeProposal);

describe("KnowledgeProposals", () => {
  beforeEach(() => {
    fetchMock.mockReset();
  });

  it("fetches on click and shows each proposal with value and confidence", async () => {
    fetchMock.mockResolvedValue(response);
    render(<Harness onAccept={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "knowledgeProposal.propose" }));
    expect(await screen.findByText('knowledgeProposal.proposed {"name":"delay_s","value":"12.5"}')).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith("ds", "L1");
    expect(screen.getByText('knowledgeProposal.proposed {"name":"ultimate_period_s","value":"40"}')).toBeInTheDocument();
    expect(screen.getAllByText(/knowledgeProposal.confidence/).length).toBeGreaterThan(0);
    expect(screen.getByText('knowledgeProposal.confidence {"level":"knowledgeProposal.level.medium"}')).toBeInTheDocument();
  });

  it("accepts one field with its key and value", async () => {
    fetchMock.mockResolvedValue(response);
    const onAccept = vi.fn();
    render(<Harness onAccept={onAccept} />);
    fireEvent.click(screen.getByRole("button", { name: "knowledgeProposal.propose" }));
    fireEvent.click(await screen.findByLabelText('knowledgeProposal.acceptField {"name":"delay_s"}'));
    expect(onAccept).toHaveBeenCalledWith({ delay_s: "12.5" });
  });

  it("accept-all takes only high-confidence fields and never the amplitude limit", async () => {
    fetchMock.mockResolvedValue(response);
    const onAccept = vi.fn();
    render(<Harness onAccept={onAccept} />);
    fireEvent.click(screen.getByRole("button", { name: "knowledgeProposal.propose" }));
    fireEvent.click(await screen.findByRole("button", { name: "knowledgeProposal.acceptHigh" }));
    expect(onAccept).toHaveBeenCalledTimes(1);
    const patch = onAccept.mock.calls[0][0];
    expect(patch).toEqual({ delay_s: "12.5", process_kind: "self_regulating" });
    expect(patch).not.toHaveProperty("amplitude_limit");
    expect(patch).not.toHaveProperty("ultimate_period_s");
  });

  it("marks the amplitude limit as must-confirm and gives it an Accept button", async () => {
    fetchMock.mockResolvedValue(response);
    render(<Harness onAccept={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "knowledgeProposal.propose" }));
    expect(await screen.findByText("knowledgeProposal.mustConfirm")).toBeInTheDocument();
    expect(screen.getByLabelText('knowledgeProposal.acceptField {"name":"amplitude_limit"}')).toBeInTheDocument();
  });

  it("shows the step-test notice and its button opens the steps", async () => {
    fetchMock.mockResolvedValue({ ...response, needs_step_test: true });
    const onOpenSteps = vi.fn();
    render(<Harness onAccept={vi.fn()} onOpenSteps={onOpenSteps} />);
    fireEvent.click(screen.getByRole("button", { name: "knowledgeProposal.propose" }));
    expect(await screen.findByText(/knowledgeProposal.needsStepTest/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "knowledgeProposal.openSteps" }));
    expect(onOpenSteps).toHaveBeenCalledTimes(1);
  });

  it("shows an alert when the request fails", async () => {
    fetchMock.mockRejectedValue(new Error("boom"));
    render(<Harness onAccept={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "knowledgeProposal.propose" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("knowledgeProposal.error");
  });
});
