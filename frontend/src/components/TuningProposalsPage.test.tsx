// frontend/src/components/TuningProposalsPage.test.tsx
// The tuning proposals view: roles, the approve rule and its confirm dialog, error mapping,
// polling cleanup, empty list, 100 rows, and server text rendered as text.

import { act, cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import * as tuningApi from "../tuningApi";
import { makeProposal, mockT, renderAs } from "../tuningTestKit";
import { TuningProposalsPage } from "./TuningProposalsPage";

const page = <TuningProposalsPage t={mockT} />;

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.useRealTimers();
});

async function open(role: string, list: tuningApi.TuningProposal[], username = role) {
  vi.spyOn(tuningApi, "fetchTuningProposals").mockResolvedValue(list);
  await renderAs(role, page, username);
  await screen.findByTestId("tuning-list");
  fireEvent.click(within(screen.getByTestId(`tuning-row-${list[0].id}`)).getByRole("button"));
  await screen.findByTestId("tuning-detail");
}

const disabled = (id: string) => screen.getByTestId(id).getAttribute("aria-disabled") === "true";

describe("detail", () => {
  it("shows the diff, confidence, caveats, labelled preview, source and expiry", async () => {
    await open("lead", [makeProposal()]);
    const items = screen.getByTestId("tuning-items");
    expect(within(items).getByTestId("tuning-item-ti")).toHaveTextContent("3045");
    expect(within(items).getByTestId("tuning-item-ti")).toHaveTextContent("FIC101.TI");
    expect(screen.getByTestId("tuning-confidence")).toHaveTextContent("tuning.proposals.confidence.high");
    expect(screen.getByTestId("tuning-confidence")).toHaveTextContent("step test");
    expect(screen.getByTestId("tuning-caveats")).toHaveTextContent("Ti is in seconds");
    expect(screen.getByTestId("tuning-preview")).toHaveTextContent("tuning.proposals.preview.label");
    expect(screen.getByTestId("tuning-source")).toHaveTextContent("st-1");
    expect(screen.getByTestId("tuning-expiry")).toHaveTextContent("tuning.proposals.expiry.left");
  });

  it("shows the review, the exact caveat key and the rollback badge for a worse verdict", async () => {
    const review = { verdict: "worse" as const, reasons: ["error_std_up"], before: { n: 100, oscillating: false }, after: { n: 90, oscillating: true } };
    await open("lead", [makeProposal({ status: "reviewed:worse", review, rollback_recommended: true, applied: { from_read: {}, to_read: {}, t: "2026-11-05T11:00:00Z", approver: "bob" } })]);
    expect(screen.getByTestId("tuning-rollback-recommended")).toHaveTextContent("tuning.proposals.rollbackRecommended");
    expect(screen.getByTestId("tuning-review-note")).toHaveTextContent("tuning.proposals.review.note");
    expect(screen.getByTestId("tuning-review-metrics")).toBeInTheDocument();
    expect(screen.getByTestId("tuning-rollback")).not.toHaveAttribute("aria-disabled");
  });

  it("renders HTML in server text as text", async () => {
    const evil = "<img src=x onerror=alert(1)>";
    await open("lead", [makeProposal({ caveats: [evil], confidence: { level: "low", reasons: [evil + "r"] } })]);
    expect(screen.getByTestId("tuning-caveats")).toHaveTextContent(evil);
    expect(document.querySelector("img")).toBeNull();
  });

  it("explains a refused record with the mapped message", async () => {
    await open("lead", [makeProposal({ status: "refused:from_mismatch", gateway_key: null })]);
    expect(screen.getByTestId("tuning-refusal")).toHaveTextContent("tuning.err.from_mismatch");
  });
});

describe("roles", () => {
  it("viewer sees the proposal but cannot approve, reject or roll back", async () => {
    await open("viewer", [makeProposal()]);
    expect(disabled("tuning-approve")).toBe(true);
    expect(disabled("tuning-rollback")).toBe(true);
    expect(disabled("tuning-reject")).toBe(false); // gw.reject is a viewer permission
  });

  it("engineer cannot approve their own proposal", async () => {
    await open("engineer", [makeProposal({ created_by: "engineer" })]);
    expect(disabled("tuning-approve")).toBe(true);
    expect(screen.getAllByTestId("disabled-reason-text").map((n) => n.textContent).join(" ")).toContain(
      "tuning.proposals.reason.selfApproval",
    );
  });

  it("a second engineer can approve; the user name is compared normalised", async () => {
    await open("engineer", [makeProposal({ created_by: "Alice " })], "bob");
    expect(disabled("tuning-approve")).toBe(false);
    cleanup();
    await open("engineer", [makeProposal({ created_by: "Alice " })], "alice");
    expect(disabled("tuning-approve")).toBe(true);
  });

  it("operator can reject but not approve or roll back", async () => {
    await open("operator", [makeProposal()]);
    expect(disabled("tuning-approve")).toBe(true);
    expect(disabled("tuning-rollback")).toBe(true);
    const reject = vi.spyOn(tuningApi, "rejectTuningProposal").mockResolvedValue(makeProposal({ status: "rejected" }));
    fireEvent.click(screen.getByTestId("tuning-reject"));
    await waitFor(() => expect(reject).toHaveBeenCalledWith("p1"));
  });

  it("lead can do everything on a queued proposal of someone else", async () => {
    await open("lead", [makeProposal()]);
    expect(disabled("tuning-approve")).toBe(false);
    expect(disabled("tuning-reject")).toBe(false);
    expect(disabled("tuning-rollback")).toBe(true); // not written yet
  });

  it("with auth disabled the actor is local-dev, so a local-dev proposal cannot be self-approved", async () => {
    await open("off", [makeProposal({ created_by: "local-dev" })]);
    expect(disabled("tuning-approve")).toBe(true);
    cleanup();
    await open("off", [makeProposal()]);
    expect(disabled("tuning-approve")).toBe(false);
  });
});

describe("approve dialog", () => {
  it("shows the diff and needs the tick before it sends", async () => {
    await open("lead", [makeProposal()]);
    const approve = vi.spyOn(tuningApi, "approveTuningProposal").mockResolvedValue(makeProposal({ status: "applied" }));
    fireEvent.click(screen.getByTestId("tuning-approve"));
    const dialog = await screen.findByTestId("tuning-approve-dialog");
    expect(within(dialog).getByTestId("tuning-items")).toBeInTheDocument();
    const confirm = screen.getByTestId("tuning-approve-confirm");
    fireEvent.click(confirm);
    expect(approve).not.toHaveBeenCalled();
    expect(confirm).toHaveAttribute("aria-disabled", "true");
    fireEvent.click(screen.getByTestId("tuning-approve-check"));
    fireEvent.click(screen.getByTestId("tuning-approve-confirm"));
    await waitFor(() => expect(approve).toHaveBeenCalledWith("p1"));
    await waitFor(() => expect(screen.queryByTestId("tuning-approve-dialog")).toBeNull());
  });

  it("shows a self-approval 403 and a gateway refusal inside the dialog", async () => {
    await open("lead", [makeProposal()]);
    const approve = vi.spyOn(tuningApi, "approveTuningProposal");
    approve.mockRejectedValueOnce(new tuningApi.TuningApiError(403, "self_approval", ""));
    fireEvent.click(screen.getByTestId("tuning-approve"));
    await screen.findByTestId("tuning-approve-dialog");
    fireEvent.click(screen.getByTestId("tuning-approve-check"));
    fireEvent.click(screen.getByTestId("tuning-approve-confirm"));
    expect(await screen.findByTestId("tuning-action-error")).toHaveTextContent("tuning.err.self_approval");
    approve.mockRejectedValueOnce(new tuningApi.TuningApiError(409, "from_mismatch", ""));
    fireEvent.click(screen.getByTestId("tuning-approve-confirm"));
    await waitFor(() => expect(screen.getByTestId("tuning-action-error")).toHaveTextContent("tuning.err.from_mismatch"));
  });

  it("maps 428 and 504", async () => {
    await open("lead", [makeProposal()]);
    const approve = vi.spyOn(tuningApi, "approveTuningProposal");
    approve.mockRejectedValueOnce(new tuningApi.TuningApiError(428, "step_up_required", ""));
    fireEvent.click(screen.getByTestId("tuning-approve"));
    await screen.findByTestId("tuning-approve-dialog");
    fireEvent.click(screen.getByTestId("tuning-approve-check"));
    fireEvent.click(screen.getByTestId("tuning-approve-confirm"));
    expect(await screen.findByTestId("tuning-action-error")).toHaveTextContent("tuning.err.stepUp");
    approve.mockRejectedValueOnce(new tuningApi.TuningApiError(504, "gateway did not answer", ""));
    fireEvent.click(screen.getByTestId("tuning-approve-confirm"));
    await waitFor(() => expect(screen.getByTestId("tuning-action-error")).toHaveTextContent("tuning.err.timeout"));
  });
});

describe("list", () => {
  it("shows the empty state", async () => {
    vi.spyOn(tuningApi, "fetchTuningProposals").mockResolvedValue([]);
    await renderAs("lead", page);
    expect(await screen.findByTestId("tuning-empty")).toHaveTextContent("tuning.proposals.empty");
  });

  it("filters by loop and by status", async () => {
    const list = [
      makeProposal({ id: "a", loop_id: "FIC1" }),
      makeProposal({ id: "b", loop_id: "TIC2", status: "applied" }),
    ];
    vi.spyOn(tuningApi, "fetchTuningProposals").mockResolvedValue(list);
    await renderAs("lead", page);
    await screen.findByTestId("tuning-row-a");
    fireEvent.change(screen.getByTestId("tuning-filter-loop"), { target: { value: "TIC2" } });
    expect(screen.queryByTestId("tuning-row-a")).toBeNull();
    expect(screen.getByTestId("tuning-row-b")).toBeInTheDocument();
    fireEvent.change(screen.getByTestId("tuning-filter-status"), { target: { value: "queued" } });
    expect(screen.getByTestId("tuning-empty")).toHaveTextContent("tuning.proposals.emptyFiltered");
  });

  it("renders 100 proposals", async () => {
    const list = Array.from({ length: 100 }, (_, i) => makeProposal({ id: `p${i}`, loop_id: `L${i % 7}` }));
    vi.spyOn(tuningApi, "fetchTuningProposals").mockResolvedValue(list);
    await renderAs("lead", page);
    await screen.findByTestId("tuning-row-p99");
    expect(screen.getAllByTestId(/^tuning-row-/)).toHaveLength(100);
  });

  it("shows a load error from the server", async () => {
    vi.spyOn(tuningApi, "fetchTuningProposals").mockRejectedValue(new tuningApi.TuningApiError(503, "gateway not running", ""));
    await renderAs("lead", page);
    expect(await screen.findByTestId("tuning-error")).toHaveTextContent("tuning.err.gatewayDown");
  });
});

describe("polling", () => {
  it("polls every 5 s and stops after unmount", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const fetchSpy = vi.spyOn(tuningApi, "fetchTuningProposals").mockResolvedValue([makeProposal()]);
    const view = await renderAs("lead", page);
    await waitFor(() => expect(fetchSpy).toHaveBeenCalledTimes(1));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000);
    });
    expect(fetchSpy.mock.calls.length).toBeGreaterThanOrEqual(2);
    view.unmount();
    const after = fetchSpy.mock.calls.length;
    await act(async () => {
      await vi.advanceTimersByTimeAsync(20000);
    });
    expect(fetchSpy.mock.calls.length).toBe(after);
  });
});
