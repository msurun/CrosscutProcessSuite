// Component tests of the Advisory page: banner, advice cards for open and blocked gates, the
// acknowledgement form (who and reason required), the chain status of the log and the empty state.
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { AdviceRecord, AdvisoryLog as AdvisoryLogData } from "../api";
import { translate } from "../i18n";
import { AckForm } from "./AckForm";
import { AdviceCard } from "./AdviceCard";
import { ProposeAction } from "./AdvicePropose";
import { AdvisoryLog } from "./AdvisoryLog";
import { AdvisoryBanner, AdvisoryPage } from "./AdvisoryPage";

const t = (key: string, params?: Record<string, string | number>) => translate("en", key, params);
const SHA = "a".repeat(64);

function advice(overrides: Partial<AdviceRecord> = {}): AdviceRecord {
  return {
    kind: "advice", advice_id: SHA, t_ns: 1_700_000_000_000_000_000, target_loop: "mill_feed",
    direction: "increase", magnitude: 3.456, activation: 0.62,
    explanation: [{ rule_id: "r1", sentence: "Mill power is low, so increase the feed.", strength: 0.62 }],
    inputs: {}, gate: { state: "open", reasons: [] }, rulebase_sha256: SHA, prev_sha256: "", ...overrides,
  };
}

function logOf(chain: AdvisoryLogData["chain"], records: AdvisoryLogData["records"] = []): AdvisoryLogData {
  return { records, total: records.length, chain };
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("banner", () => {
  it("is a note that says nothing is written to the plant", () => {
    render(<AdvisoryBanner t={t} />);
    expect(screen.getByRole("note")).toHaveTextContent("Advisory only: nothing is written to the plant; decisions here are recorded in a log.");
  });
});

describe("AdviceCard", () => {
  it("shows direction as icon and word, magnitude, activation (not confidence) and an open gate", () => {
    render(<ul><AdviceCard advice={advice()} t={t} /></ul>);
    expect(screen.getByText("increase")).toBeInTheDocument();
    expect(screen.getByText(/magnitude 3\.46/)).toBeInTheDocument();
    expect(screen.getByText(/activation 0\.62/)).toBeInTheDocument();
    expect(screen.getByText("gate: open")).toBeInTheDocument();
    expect(screen.getByText("Mill power is low, so increase the feed.")).toBeInTheDocument();
    expect(screen.queryByText(/confidence/i)).toBeNull();
  });

  it("shows a blocked gate with its reasons and no magnitude", () => {
    const blocked = advice({ direction: "hold", magnitude: null, gate: { state: "blocked", reasons: ["mill_feed:manual"] } });
    render(<ul><AdviceCard advice={blocked} t={t} /></ul>);
    expect(screen.getByText("gate: blocked")).toBeInTheDocument();
    expect(screen.getByText(/mill_feed:manual/)).toBeInTheDocument();
    expect(screen.getByText(/no magnitude/)).toBeInTheDocument();
    expect(screen.getByText("hold")).toBeInTheDocument();
  });

  it("offers the three decision buttons only when it can record decisions", () => {
    const { rerender } = render(<ul><AdviceCard advice={advice()} t={t} /></ul>);
    expect(screen.queryByRole("button", { name: /Record decision/ })).toBeNull();
    rerender(<ul><AdviceCard advice={advice()} t={t} onDecide={async () => undefined} /></ul>);
    expect(screen.getAllByRole("button", { name: /^Record decision: / })).toHaveLength(3);
  });
});

describe("AckForm", () => {
  it("does not submit without who and a reason", () => {
    const onSubmit = vi.fn().mockResolvedValue(undefined);
    render(<AckForm decision="accepted" t={t} onSubmit={onSubmit} onCancel={() => undefined} />);
    fireEvent.click(screen.getByRole("button", { name: "Record decision" }));
    expect(screen.getByRole("alert")).toHaveTextContent("Choose a reason and enter who decided.");
    expect(onSubmit).not.toHaveBeenCalled();
    fireEvent.change(screen.getByLabelText("Reason"), { target: { value: "other" } });
    fireEvent.change(screen.getByLabelText("Who decided"), { target: { value: "   " } });
    fireEvent.click(screen.getByRole("button", { name: "Record decision" }));
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("submits the draft when both are given", async () => {
    const onSubmit = vi.fn().mockResolvedValue(undefined);
    render(<AckForm decision="rejected" t={t} onSubmit={onSubmit} onCancel={() => undefined} />);
    fireEvent.change(screen.getByLabelText("Reason"), { target: { value: "equipment_limit" } });
    fireEvent.change(screen.getByLabelText("Who decided"), { target: { value: "Ola" } });
    fireEvent.change(screen.getByLabelText("Note (optional)"), { target: { value: "valve worn" } });
    fireEvent.click(screen.getByRole("button", { name: "Record decision" }));
    await waitFor(() => expect(onSubmit).toHaveBeenCalledWith({ reasonCode: "equipment_limit", who: "Ola", note: "valve worn" }));
  });
});

describe("AdvisoryLog", () => {
  const render_ = (log: AdvisoryLogData) =>
    render(<AdvisoryLog supervisorId="sv" log={log} error={null} t={t} onChanged={() => undefined} />);

  it("shows a verified chain as a status", () => {
    render_(logOf({ ok: true, records: 2, first_broken_index: null, reason: "ok" }));
    expect(screen.getByRole("status")).toHaveTextContent("chain verified (2 records)");
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("shows a broken chain as an alert naming the record", () => {
    render_(logOf({ ok: false, records: 5, first_broken_index: 2, reason: "sha256 does not match record" }));
    expect(screen.getByRole("alert")).toHaveTextContent("chain broken at record 3: sha256 does not match record");
  });

  it("shows the recorded decision of an advice", () => {
    const ack = { kind: "ack" as const, advice_id: SHA, decision: "accepted" as const, reason_code: "other", who: "Ola", t_ns: 1_700_000_100_000_000_000, prev_sha256: "" };
    render_(logOf({ ok: true, records: 2, first_broken_index: null, reason: "ok" }, [advice(), ack]));
    expect(screen.getByText(/Decision recorded: accepted by Ola/)).toBeInTheDocument();
  });
});

describe("AdvisoryPage", () => {
  it("explains the empty state and offers Load example, with the banner", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, status: 200, statusText: "OK", json: async () => [] }));
    render(<AdvisoryPage datasetId="ds" t={t} />);
    expect(screen.getByRole("note")).toBeInTheDocument();
    expect(await screen.findByRole("button", { name: "Load example" })).toBeInTheDocument();
    expect(screen.getByText(/configuration is a JSON file/)).toBeInTheDocument();
  });
});

describe("ProposeAction", () => {
  const RESULT = {
    proposal: { target_tag: "FIC1.SP", value: 51.25, proposer: "supervisor:sv", t_ns: 1, reason: "Mill power is low" },
    decision: { accepted: true, reason_code: "queued" }, advice_id: SHA, mode: "confirm", queues_for_approval: true,
  };

  it("asks for confirmation first and sends nothing before it", () => {
    const onPropose = vi.fn();
    render(<ProposeAction onPropose={onPropose} t={t} />);
    fireEvent.click(screen.getByRole("button", { name: "Propose setpoint change" }));
    expect(screen.getByText(/this page writes nothing to the plant/)).toBeInTheDocument();
    expect(onPropose).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.getByRole("button", { name: "Propose setpoint change" })).toBeInTheDocument();
  });

  it("shows the proposal and that it is queued for approval", async () => {
    const onPropose = vi.fn().mockResolvedValue(RESULT);
    render(<ProposeAction onPropose={onPropose} t={t} />);
    fireEvent.click(screen.getByRole("button", { name: "Propose setpoint change" }));
    fireEvent.click(screen.getByRole("button", { name: "Send proposal" }));
    const shown = await screen.findByTestId("propose-result");
    expect(shown).toHaveTextContent("set FIC1.SP to 51.25");
    expect(shown).toHaveTextContent("needs a human approval");
    expect(onPropose).toHaveBeenCalledTimes(1);
  });

  it("shows the server's refusal code as an alert", async () => {
    const onPropose = vi.fn().mockRejectedValue(new Error("already_proposed"));
    render(<ProposeAction onPropose={onPropose} t={t} />);
    fireEvent.click(screen.getByRole("button", { name: "Propose setpoint change" }));
    fireEvent.click(screen.getByRole("button", { name: "Send proposal" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("already_proposed");
  });

  it("is offered on logged advice that moves the setpoint, not on hold", () => {
    const onPropose = vi.fn();
    const { rerender } = render(<ul><AdviceCard advice={advice()} t={t} onPropose={onPropose} /></ul>);
    expect(screen.getByRole("button", { name: "Propose setpoint change" })).toBeInTheDocument();
    rerender(<ul><AdviceCard advice={advice({ direction: "hold", magnitude: null })} t={t} onPropose={onPropose} /></ul>);
    expect(screen.queryByRole("button", { name: "Propose setpoint change" })).toBeNull();
  });
});
