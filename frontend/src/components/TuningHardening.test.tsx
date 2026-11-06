// frontend/src/components/TuningHardening.test.tsx
// The hardened tuning write path in the proposals view: the "applying" and foreign_pending
// statuses, applied blocks with unknown values, the unavailable rollback and review, the new
// error codes in the dialogs, and the paginated list with "Load more".

import { act, cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import * as tuningApi from "../tuningApi";
import { makeProposal, mockT, renderAs } from "../tuningTestKit";
import { TuningProposalsPage } from "./TuningProposalsPage";

const page = <TuningProposalsPage t={mockT} />;
const T0 = "2026-11-05T11:00:00Z";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.useRealTimers();
});

async function open(list: tuningApi.TuningProposal[], role = "lead") {
  vi.spyOn(tuningApi, "fetchTuningProposals").mockResolvedValue(list);
  await renderAs(role, page, "bob");
  await screen.findByTestId("tuning-list");
  fireEvent.click(within(screen.getByTestId(`tuning-row-${list[0].id}`)).getByRole("button"));
  await screen.findByTestId("tuning-detail");
}

const disabled = (id: string) => screen.getByTestId(id).getAttribute("aria-disabled") === "true";

const unverified = (over: Partial<tuningApi.TuningApplied> = {}): tuningApi.TuningApplied => ({
  from_read: { "FIC101.GAIN": null, "FIC101.TI": null },
  to_read: { "FIC101.GAIN": null, "FIC101.TI": null },
  t: T0,
  approver: "bob",
  source: "gateway_reply",
  invalid: "audit_unverified",
  ...over,
});

describe("applying", () => {
  it("shows the chip, the explanation with a gateway link, and disables every action", async () => {
    await open([makeProposal({ status: "applying" })]);
    expect(screen.getAllByText("tuning.proposals.status.applying").length).toBeGreaterThan(0);
    const notice = screen.getByTestId("tuning-applying");
    expect(notice).toHaveTextContent("tuning.proposals.applying.text");
    expect(within(notice).getByRole("link")).toHaveAttribute("href", expect.stringContaining("/gateway"));
    expect(disabled("tuning-approve")).toBe(true);
    expect(disabled("tuning-reject")).toBe(true);
    expect(disabled("tuning-rollback")).toBe(true);
    expect(screen.getAllByTestId("disabled-reason-text").map((n) => n.textContent).join(" ")).toContain(
      "tuning.proposals.reason.applying",
    );
  });

  it("keeps polling while applying and shows the applied record once the audit resolves", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const fetchSpy = vi
      .spyOn(tuningApi, "fetchTuningProposals")
      .mockResolvedValueOnce([makeProposal({ status: "applying" })])
      .mockResolvedValue([makeProposal({ status: "applied", applied: unverified({ source: "audit", chain_ok: true, invalid: undefined, from_read: { "FIC101.GAIN": 1, "FIC101.TI": 30 }, to_read: { "FIC101.GAIN": 1.5, "FIC101.TI": 45 } }) })]);
    await renderAs("lead", page, "bob");
    fireEvent.click(within(await screen.findByTestId("tuning-row-p1")).getByRole("button"));
    expect(await screen.findByTestId("tuning-applying")).toBeInTheDocument();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000);
    });
    expect(fetchSpy.mock.calls.length).toBeGreaterThanOrEqual(2);
    await waitFor(() => expect(screen.queryByTestId("tuning-applying")).toBeNull());
    expect(screen.getByTestId("tuning-applied-source")).toHaveTextContent("tuning.proposals.applied.source.audit");
    expect(screen.queryByTestId("tuning-applied-warning")).toBeNull();
  });

  it("a timed-out approve shows the applying hint and re-reads the list", async () => {
    await open([makeProposal()]);
    const fetchSpy = vi.mocked(tuningApi.fetchTuningProposals);
    vi.spyOn(tuningApi, "approveTuningProposal").mockRejectedValue(new tuningApi.TuningApiError(504, "gateway did not answer", ""));
    fireEvent.click(screen.getByTestId("tuning-approve"));
    await screen.findByTestId("tuning-approve-dialog");
    fireEvent.click(screen.getByTestId("tuning-approve-check"));
    const before = fetchSpy.mock.calls.length;
    fireEvent.click(screen.getByTestId("tuning-approve-confirm"));
    expect(await screen.findByTestId("tuning-action-error")).toHaveTextContent("tuning.err.timeout");
    await waitFor(() => expect(fetchSpy.mock.calls.length).toBeGreaterThan(before));
  });

  it("shows the 409 applying error of a second approve", async () => {
    await open([makeProposal()]);
    vi.spyOn(tuningApi, "approveTuningProposal").mockRejectedValue(new tuningApi.TuningApiError(409, "applying", ""));
    fireEvent.click(screen.getByTestId("tuning-approve"));
    await screen.findByTestId("tuning-approve-dialog");
    fireEvent.click(screen.getByTestId("tuning-approve-check"));
    fireEvent.click(screen.getByTestId("tuning-approve-confirm"));
    expect(await screen.findByTestId("tuning-action-error")).toHaveTextContent("tuning.err.applying");
  });
});

describe("refused:foreign_pending", () => {
  it("shows a chip with its own text and the explanatory message", async () => {
    await open([makeProposal({ status: "refused:foreign_pending", gateway_key: null })]);
    expect(screen.getByTestId("tuning-refusal")).toHaveTextContent("tuning.err.foreign_pending");
    expect(screen.getAllByText(/tuning\.proposals\.refused\.foreign_pending/).length).toBeGreaterThan(0);
  });

  it("maps a 409 foreign_pending answer to the create / approve dialog text", async () => {
    await open([makeProposal()]);
    vi.spyOn(tuningApi, "approveTuningProposal").mockRejectedValue(new tuningApi.TuningApiError(409, "foreign_pending", ""));
    fireEvent.click(screen.getByTestId("tuning-approve"));
    await screen.findByTestId("tuning-approve-dialog");
    fireEvent.click(screen.getByTestId("tuning-approve-check"));
    fireEvent.click(screen.getByTestId("tuning-approve-confirm"));
    expect(await screen.findByTestId("tuning-action-error")).toHaveTextContent("tuning.err.foreign_pending");
  });
});

describe("applied with unknown values", () => {
  it.each(["audit_unverified", "audit_chain_broken", "param_changed_externally"])(
    "shows %s as unknown values with a warning and an unavailable rollback",
    async (invalid) => {
      await open([makeProposal({ status: "applied", applied: unverified({ invalid }) })]);
      const values = screen.getByTestId("tuning-applied-values");
      expect(within(values).getAllByText("tuning.proposals.applied.unknown")).toHaveLength(4);
      const warning = screen.getByTestId("tuning-applied-warning");
      expect(warning).toHaveTextContent(`tuning.proposals.applied.invalid.${invalid}`);
      expect(warning).toHaveTextContent("tuning.proposals.applied.unavailable");
      expect(disabled("tuning-rollback")).toBe(true);
      expect(screen.getAllByTestId("disabled-reason-text").map((n) => n.textContent).join(" ")).toContain(
        "tuning.proposals.reason.appliedUnverified",
      );
    },
  );

  it("shows the source of audited values and no warning for a trusted block", async () => {
    const applied = unverified({ source: "audit", chain_ok: true, invalid: undefined, from_read: { "FIC101.GAIN": 1, "FIC101.TI": 30 }, to_read: { "FIC101.GAIN": 1.5, "FIC101.TI": 45 } });
    await open([makeProposal({ status: "applied", applied })]);
    expect(screen.getByTestId("tuning-applied-source")).toHaveTextContent("tuning.proposals.applied.source.audit");
    expect(screen.queryByTestId("tuning-applied-warning")).toBeNull();
    expect(within(screen.getByTestId("tuning-applied-values")).queryByText("tuning.proposals.applied.unknown")).toBeNull();
    expect(disabled("tuning-rollback")).toBe(false);
  });

  it("shows an insufficient_data review with the reason and the unavailable note", async () => {
    const review = { verdict: "insufficient_data" as const, reasons: ["applied_unverified"] };
    await open([makeProposal({ status: "reviewed:insufficient_data", review, applied: unverified() })]);
    expect(screen.getByTestId("tuning-review")).toHaveTextContent("applied_unverified");
    expect(screen.getByTestId("tuning-review-unavailable")).toHaveTextContent("tuning.proposals.review.unavailable");
  });

  it("shows the review reason param_changed_externally and flags the applied block", async () => {
    const review = { verdict: "insufficient_data" as const, reasons: ["param_changed_externally"] };
    const applied = unverified({ source: "audit", chain_ok: true, invalid: "param_changed_externally", from_read: { "FIC101.GAIN": 1 }, to_read: { "FIC101.GAIN": 2 } });
    await open([makeProposal({ status: "reviewed:insufficient_data", review, applied })]);
    expect(screen.getByTestId("tuning-review")).toHaveTextContent("param_changed_externally");
    expect(screen.getByTestId("tuning-applied-warning")).toHaveTextContent("param_changed_externally");
  });

  it("maps a 409 applied_unverified rollback answer", async () => {
    const applied = unverified({ source: "audit", chain_ok: true, invalid: undefined, from_read: { "FIC101.GAIN": 1, "FIC101.TI": 30 }, to_read: { "FIC101.GAIN": 1.5, "FIC101.TI": 45 } });
    await open([makeProposal({ status: "applied", applied })]);
    vi.spyOn(tuningApi, "rollbackTuningProposal").mockRejectedValue(new tuningApi.TuningApiError(409, "applied_unverified", ""));
    fireEvent.click(screen.getByTestId("tuning-rollback"));
    await screen.findByTestId("tuning-rollback-dialog");
    fireEvent.click(screen.getByTestId("tuning-rollback-confirm"));
    expect(await screen.findByTestId("tuning-action-error")).toHaveTextContent("tuning.err.applied_unverified");
  });

  it("maps a 422 no_history and a 409 no_live_values answer", async () => {
    await open([makeProposal({ status: "applied", applied: unverified({ source: "audit", chain_ok: true, invalid: undefined, from_read: { a: 1 }, to_read: { a: 2 } }) })]);
    const rollback = vi.spyOn(tuningApi, "rollbackTuningProposal");
    rollback.mockRejectedValueOnce(new tuningApi.TuningApiError(422, "no_history", "no_history"));
    fireEvent.click(screen.getByTestId("tuning-rollback"));
    await screen.findByTestId("tuning-rollback-dialog");
    fireEvent.click(screen.getByTestId("tuning-rollback-confirm"));
    expect(await screen.findByTestId("tuning-action-error")).toHaveTextContent("tuning.err.no_history");
    rollback.mockRejectedValueOnce(new tuningApi.TuningApiError(409, "no_live_values", ""));
    fireEvent.click(screen.getByTestId("tuning-rollback-confirm"));
    await waitFor(() => expect(screen.getByTestId("tuning-action-error")).toHaveTextContent("tuning.err.no_live_values"));
  });
});

describe("pagination", () => {
  const rows = (from: number, count: number) =>
    Array.from({ length: count }, (_, i) => makeProposal({ id: `p${from + i}`, loop_id: `L${(from + i) % 5}` }));

  function pagedMock() {
    return vi.spyOn(tuningApi, "fetchTuningProposals").mockImplementation(async (filter) => {
      const offset = filter?.offset ?? 0;
      return rows(offset, Math.min(filter?.limit ?? 100, Math.max(0, 130 - offset)));
    });
  }

  it("asks for a page of 100, offers Load more for a full page and announces the result", async () => {
    const spy = pagedMock();
    await renderAs("lead", page);
    await screen.findByTestId("tuning-row-p99");
    expect(spy).toHaveBeenCalledWith({ limit: 100, offset: 0 });
    expect(screen.getByTestId("tuning-count")).toHaveTextContent("tuning.proposals.countMore");
    fireEvent.click(screen.getByTestId("tuning-load-more"));
    await screen.findByTestId("tuning-row-p129");
    expect(spy).toHaveBeenCalledWith({ limit: 100, offset: 100 });
    expect(screen.getAllByTestId(/^tuning-row-/)).toHaveLength(130);
    const live = screen.getByTestId("tuning-announce");
    expect(live).toHaveAttribute("aria-live", "polite");
    expect(live).toHaveTextContent('tuning.proposals.loadedMore{"added":30,"shown":130}');
    expect(screen.queryByTestId("tuning-load-more")).toBeNull(); // the last page was short
    expect(screen.getByTestId("tuning-count")).toHaveTextContent("tuning.proposals.count");
  });

  it("polls only the loaded range: one page before Load more, two after", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const spy = pagedMock();
    await renderAs("lead", page);
    await screen.findByTestId("tuning-row-p99");
    expect(spy.mock.calls.every(([f]) => f?.offset === 0)).toBe(true);
    fireEvent.click(screen.getByTestId("tuning-load-more"));
    await screen.findByTestId("tuning-row-p129");
    spy.mockClear();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000);
    });
    const offsets = spy.mock.calls.map(([f]) => f?.offset);
    expect(offsets).toContain(0);
    expect(offsets).toContain(100);
    expect(Math.max(...(offsets as number[]))).toBe(100); // never beyond the loaded range
  });

  it("shows no Load more button for a short first page", async () => {
    vi.spyOn(tuningApi, "fetchTuningProposals").mockResolvedValue(rows(0, 3));
    await renderAs("lead", page);
    await screen.findByTestId("tuning-row-p2");
    expect(screen.queryByTestId("tuning-load-more")).toBeNull();
    expect(screen.getByTestId("tuning-count")).toHaveTextContent('"shown":3');
  });
});
