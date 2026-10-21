// Tests of the advisory supervisor client functions in api.ts (fetch is mocked) and of the pure
// helpers in advisory.ts: URLs, request bodies, error mapping, ack state and form validation.
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  ackAdvice,
  adviseNow,
  ApiError,
  fetchAdvisoryLog,
  fetchSupervisorConfig,
  fetchSupervisors,
  replaySupervisor,
  saveSupervisorConfig,
  type AckRecord,
  type AdviceRecord,
} from "./api";
import { ackIsValid, advicesNewestFirst, latestAcks, validateAck } from "./advisory";
import { EXAMPLE_CONFIG } from "./components/AdvisoryState";

function respond(body: unknown, ok = true, status = 200) {
  return { ok, status, statusText: "ST", json: async () => body };
}

function stubFetch(response: unknown): ReturnType<typeof vi.fn> {
  const mock = vi.fn().mockResolvedValue(response);
  vi.stubGlobal("fetch", mock);
  return mock;
}

/** The parsed JSON body of the first call of a fetch mock. */
function sentBody(mock: ReturnType<typeof vi.fn>): unknown {
  return JSON.parse((mock.mock.calls[0][1] as { body: string }).body);
}

afterEach(() => vi.unstubAllGlobals());

describe("supervisor config calls", () => {
  it("lists supervisors and reads one config", async () => {
    const list = stubFetch(respond(["a"]));
    expect(await fetchSupervisors()).toEqual(["a"]);
    expect(list).toHaveBeenCalledWith("/api/supervisors");
    const one = stubFetch(respond(EXAMPLE_CONFIG));
    expect(await fetchSupervisorConfig("mill feed")).toEqual(EXAMPLE_CONFIG);
    expect(one).toHaveBeenCalledWith("/api/supervisors/mill%20feed");
  });

  it("puts a config under its own id", async () => {
    const mock = stubFetch(respond(EXAMPLE_CONFIG));
    await saveSupervisorConfig(EXAMPLE_CONFIG);
    expect(mock.mock.calls[0][0]).toBe("/api/supervisors/mill_feed_advisor");
    expect(mock.mock.calls[0][1].method).toBe("PUT");
    expect(sentBody(mock)).toEqual(EXAMPLE_CONFIG);
  });

  it("the bundled example is advisory only", () => {
    expect(EXAMPLE_CONFIG.mode).toBe("advisory");
    expect(EXAMPLE_CONFIG.target_loop).toBe("mill_feed");
  });
});

describe("advice calls", () => {
  it("advise-now posts the time (null = end of record)", async () => {
    const mock = stubFetch(respond({ advice: null, gate: { state: "blocked", reasons: ["x"] } }));
    const result = await adviseNow("ds 1", "sv", undefined);
    expect(mock.mock.calls[0][0]).toBe("/api/datasets/ds%201/supervisor/sv/advise");
    expect(sentBody(mock)).toEqual({ t_s: null });
    expect(result.gate.state).toBe("blocked");
  });

  it("replay sends window, step and the record flag, default off", async () => {
    const mock = stubFetch(respond({ advices: [], recorded: 0 }));
    await replaySupervisor("ds", "sv", { windowS: 600, stepS: 300 });
    expect(mock.mock.calls[0][0]).toBe("/api/datasets/ds/supervisor/sv/replay");
    expect(sentBody(mock)).toMatchObject({ window_s: 600, step_s: 300, record: false });
    const recording = stubFetch(respond({ advices: [], recorded: 3 }));
    await replaySupervisor("ds", "sv", { record: true });
    expect(sentBody(recording)).toMatchObject({ record: true });
  });

  it("reads the log from an index", async () => {
    const mock = stubFetch(respond({ records: [], total: 0, chain: { ok: true, records: 0, first_broken_index: null, reason: "ok" } }));
    await fetchAdvisoryLog("sv", 4);
    expect(mock).toHaveBeenCalledWith("/api/supervisors/sv/log?since_index=4");
  });

  it("ack posts the decision fields in the server's names", async () => {
    const mock = stubFetch(respond({ kind: "ack" }));
    await ackAdvice("sv", "ab12", { decision: "accepted", reasonCode: "other", who: "Ola" });
    expect(mock.mock.calls[0][0]).toBe("/api/supervisors/sv/log/ab12/ack");
    expect(sentBody(mock)).toEqual({ decision: "accepted", reason_code: "other", who: "Ola", note: "" });
  });

  it("maps a 422 detail to an ApiError", async () => {
    stubFetch(respond({ detail: "who and reason_code must not be empty" }, false, 422));
    await expect(ackAdvice("sv", "ab", { decision: "accepted", reasonCode: "x", who: "y" })).rejects.toMatchObject({
      status: 422,
      message: "who and reason_code must not be empty",
    });
    expect(new ApiError(422, "m")).toBeInstanceOf(Error);
  });
});

describe("advisory helpers", () => {
  it("requires who and a reason; blank who does not count", () => {
    expect(ackIsValid(validateAck({ reasonCode: "other", who: "Ola", note: "" }))).toBe(true);
    expect(validateAck({ reasonCode: "", who: "Ola", note: "" })).toEqual({ who: false, reasonCode: true });
    expect(validateAck({ reasonCode: "other", who: "  ", note: "" })).toEqual({ who: true, reasonCode: false });
  });

  it("keeps the newest ack of each advice", () => {
    const ack = (decision: AckRecord["decision"], t_ns: number): AckRecord =>
      ({ kind: "ack", advice_id: "a", decision, reason_code: "other", who: "w", t_ns, prev_sha256: "" });
    const advice = { kind: "advice", advice_id: "a" } as AdviceRecord;
    const acks = latestAcks([advice, ack("deferred", 1), ack("accepted", 2)]);
    expect(acks.get("a")?.decision).toBe("accepted");
    expect(acks.size).toBe(1);
  });

  it("lists each advice id once, newest first", () => {
    const one = (id: string, t_ns: number) => ({ kind: "advice", advice_id: id, t_ns }) as AdviceRecord;
    const ids = advicesNewestFirst([one("a", 1), one("b", 2), one("a", 1)]).map((a) => a.advice_id);
    expect(ids).toEqual(["b", "a"]);
  });
});
