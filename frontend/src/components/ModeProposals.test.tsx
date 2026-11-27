// Tests of the mode-proposal panel: propose, edit a threshold, accept (PUT site), reject and errors.
// The clients are mocked; t returns the key with its variables.
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import * as api from "../api";
import * as proposals from "../modeProposalApi";
import { ModeProposals } from "./ModeProposals";

vi.mock("../modeProposalApi");

const t = (key: string, vars?: Record<string, string | number>) => (vars ? `${key} ${JSON.stringify(vars)}` : key);
const evidence = { kind: "bimodal_gap", share: 0.31, thresholds: { threshold: 3 }, windows: [[0, 60]] as [number, number][], events: 3, detail: "two clusters" };
const response: proposals.ModeProposalResponse = {
  dataset: "ds",
  equipment: [{ id: "PMP7", confidence: "high", evidence, entry: { id: "PMP7", name: "PMP7", level: "equipment", tags: ["PMP7_RUN", "PMP7_CURR"] } }],
  modes: [{
    id: "PMP7_stopped", confidence: "medium", evidence, scope_new: true,
    entry: { id: "PMP7_stopped", name: "PMP7 stopped", scope: "PMP7", condition: { match: "all", clauses: [{ tag: "PMP7_CURR", op: "<=", value: 3 }] } },
  }],
};

async function openProposals() {
  render(<ModeProposals t={t} />);
  await screen.findByRole("option", { name: "ds" });
  fireEvent.click(screen.getByRole("button", { name: "modeProposal.propose" }));
  await screen.findByText("PMP7 stopped");
}

beforeEach(() => {
  vi.restoreAllMocks();
  vi.spyOn(api, "fetchDatasets").mockResolvedValue([{ id: "ds" } as api.DatasetSummary]);
  vi.mocked(proposals.fetchModeProposals).mockResolvedValue(response);
});

describe("ModeProposals", () => {
  it("lists modes and groups with confidence and evidence", async () => {
    await openProposals();
    expect(proposals.fetchModeProposals).toHaveBeenCalledWith("ds");
    expect(screen.getByText("PMP7")).toBeTruthy();
    expect(screen.getAllByText(/modeProposal.confidence/).length).toBe(2);
    expect(screen.getAllByText(/modeProposal.share/).length).toBe(2);
  });

  it("accepts a mode with the edited threshold and saves the site once", async () => {
    await openProposals();
    vi.spyOn(api, "getJson").mockResolvedValue({ tags: [] });
    const send = vi.spyOn(api, "sendJson").mockResolvedValue({});
    fireEvent.change(screen.getByLabelText(/modeProposal.threshold/), { target: { value: "4.5" } });
    fireEvent.click(screen.getByRole("button", { name: /modeProposal.acceptItem.*PMP7 stopped/ }));
    await screen.findByText(/modeProposal.saved/);
    const [method, url, body] = send.mock.calls[0] as [string, string, { modes: { condition: { clauses: { value: number }[] } }[]; equipment: { id: string }[] }];
    expect(method).toBe("PUT");
    expect(url).toBe("/api/site");
    expect(body.modes[0].condition.clauses[0].value).toBe(4.5);
    expect(body.equipment.map((e) => e.id)).toContain("PMP7");
    expect(screen.queryByText("PMP7 stopped")).toBeNull();
  });

  it("refuses a threshold that is not a number and saves nothing", async () => {
    await openProposals();
    const send = vi.spyOn(api, "sendJson").mockResolvedValue({});
    fireEvent.change(screen.getByLabelText(/modeProposal.threshold/), { target: { value: "x" } });
    fireEvent.click(screen.getByRole("button", { name: /modeProposal.acceptItem.*PMP7 stopped/ }));
    await screen.findByText("modeProposal.badValue");
    expect(send).not.toHaveBeenCalled();
  });

  it("rejecting hides the proposal without saving", async () => {
    await openProposals();
    const send = vi.spyOn(api, "sendJson").mockResolvedValue({});
    fireEvent.click(screen.getByRole("button", { name: /modeProposal.rejectItem.*PMP7 stopped/ }));
    await waitFor(() => expect(screen.queryByText("PMP7 stopped")).toBeNull());
    expect(send).not.toHaveBeenCalled();
  });

  it("shows a backend error as an alert", async () => {
    vi.mocked(proposals.fetchModeProposals).mockRejectedValue(new api.ApiError(404, "unknown dataset", { code: null, field: null, findingCodes: [] }));
    render(<ModeProposals t={t} />);
    await screen.findByRole("option", { name: "ds" });
    fireEvent.click(screen.getByRole("button", { name: "modeProposal.propose" }));
    expect((await screen.findByRole("alert")).textContent).toContain("unknown dataset");
  });
});
