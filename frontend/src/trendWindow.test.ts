import { describe, expect, it } from "vitest";
import {
  TrendWindow,
  WIDTH_PRESETS_S,
  resolveWindow,
  panWindow,
  withWidth,
  isLive,
  validateWindow,
} from "./trendWindow";

describe("trendWindow", () => {
  describe("WIDTH_PRESETS_S", () => {
    it("should have the correct presets", () => {
      expect(WIDTH_PRESETS_S).toEqual([
        { id: "15m", seconds: 900 },
        { id: "1h", seconds: 3600 },
        { id: "8h", seconds: 28800 },
        { id: "24h", seconds: 86400 },
        { id: "7d", seconds: 604800 },
        { id: "30d", seconds: 2592000 },
      ]);
    });
  });

  describe("resolveWindow", () => {
    it("should resolve a relative window without dataEndNs", () => {
      const nowMs = 1625097600000; // 2021-06-30T00:00:00.000Z
      const w: TrendWindow = { kind: "relative", last_s: 3600 };
      const result = resolveWindow(w, nowMs);
      expect(result).toEqual({
        startNs: 1625097600000000000 - 3600 * 1e9,
        endNs: 1625097600000000000,
      });
    });

    it("should resolve a relative window with dataEndNs", () => {
      const nowMs = 1625097600000; // 2021-06-30T00:00:00.000Z
      const dataEndNs = 1625097600000000000 - 1800 * 1e9; // 30 minutes earlier
      const w: TrendWindow = { kind: "relative", last_s: 3600 };
      const result = resolveWindow(w, nowMs, dataEndNs);
      expect(result).toEqual({
        startNs: dataEndNs - 3600 * 1e9,
        endNs: dataEndNs,
      });
    });

    it("should resolve an absolute window", () => {
      const nowMs = 1625097600000; // 2021-07-01T00:00:00.000Z
      const w: TrendWindow = {
        kind: "absolute",
        start_utc: "2021-06-30T00:00:00.000Z",
        end_utc: "2021-06-30T01:00:00.000Z",
      };
      const result = resolveWindow(w, nowMs);
      expect(result).toEqual({
        startNs: 1625011200000000000,
        endNs: 1625011200000000000 + 3600 * 1e9,
      });
    });
  });

  describe("panWindow", () => {
    it("should pan a relative window left", () => {
      const nowMs = 1625097600000; // 2021-06-30T00:00:00.000Z
      const w: TrendWindow = { kind: "relative", last_s: 3600, live: true };
      const result = panWindow(w, -1, nowMs);
      expect(result).toEqual({ kind: "relative", last_s: 3600, live: true });
    });

    it("should pan a relative window right", () => {
      const nowMs = 1625097600000; // 2021-06-30T00:00:00.000Z
      const w: TrendWindow = { kind: "relative", last_s: 3600, live: true };
      const result = panWindow(w, 1, nowMs);
      expect(result).toEqual({ kind: "relative", last_s: 3600, live: true });
    });

    it("should pan an absolute window left", () => {
      const nowMs = 1625097600000; // 2021-06-30T00:00:00.000Z
      const w: TrendWindow = {
        kind: "absolute",
        start_utc: "2021-06-30T00:00:00.000Z",
        end_utc: "2021-06-30T01:00:00.000Z",
      };
      const result = panWindow(w, -1, nowMs);
      expect(result).toEqual({
        kind: "absolute",
        start_utc: "2021-06-29T23:00:00.000Z",
        end_utc: "2021-06-30T00:00:00.000Z",
      });
    });

    it("should pan an absolute window right", () => {
      const nowMs = 1625097600000; // 2021-06-30T00:00:00.000Z
      const w: TrendWindow = {
        kind: "absolute",
        start_utc: "2021-06-30T00:00:00.000Z",
        end_utc: "2021-06-30T01:00:00.000Z",
      };
      const result = panWindow(w, 1, nowMs);
      expect(result).toEqual({
        kind: "absolute",
        start_utc: "2021-06-30T01:00:00.000Z",
        end_utc: "2021-06-30T02:00:00.000Z",
      });
    });
  });

  describe("withWidth", () => {
    it("should set the width of a relative window", () => {
      const nowMs = 1625097600000; // 2021-06-30T00:00:00.000Z
      const w: TrendWindow = { kind: "relative", last_s: 3600, live: true };
      const result = withWidth(w, 7200, nowMs);
      expect(result).toEqual({ kind: "relative", last_s: 7200, live: true });
    });

    it("should set the width of an absolute window", () => {
      const nowMs = 1625097600000; // 2021-06-30T00:00:00.000Z
      const w: TrendWindow = {
        kind: "absolute",
        start_utc: "2021-06-30T00:00:00.000Z",
        end_utc: "2021-06-30T01:00:00.000Z",
      };
      const result = withWidth(w, 7200, nowMs);
      expect(result).toEqual({
        kind: "absolute",
        start_utc: "2021-06-29T23:00:00.000Z",
        end_utc: "2021-06-30T01:00:00.000Z",
      });
    });
  });

  describe("isLive", () => {
    it("should return true for a live relative window", () => {
      const w: TrendWindow = { kind: "relative", last_s: 3600, live: true };
      expect(isLive(w)).toBe(true);
    });

    it("should return false for a non-live relative window", () => {
      const w: TrendWindow = { kind: "relative", last_s: 3600, live: false };
      expect(isLive(w)).toBe(false);
    });

    it("should return false for an absolute window", () => {
      const w: TrendWindow = {
        kind: "absolute",
        start_utc: "2021-06-30T00:00:00.000Z",
        end_utc: "2021-06-30T01:00:00.000Z",
      };
      expect(isLive(w)).toBe(false);
    });
  });

  describe("validateWindow", () => {
    it("should validate a relative window", () => {
      const w: TrendWindow = { kind: "relative", last_s: 3600 };
      expect(validateWindow(w)).toEqual([]);
    });

    it("should invalidate a relative window with last_s < 60", () => {
      const w: TrendWindow = { kind: "relative", last_s: 59 };
      expect(validateWindow(w)).toEqual(["Relative window must be at least 60 seconds."]);
    });

    it("should validate an absolute window", () => {
      const w: TrendWindow = {
        kind: "absolute",
        start_utc: "2021-06-30T00:00:00.000Z",
        end_utc: "2021-06-30T01:00:00.000Z",
      };
      expect(validateWindow(w)).toEqual([]);
    });

    it("should invalidate an absolute window with end <= start", () => {
      const w: TrendWindow = {
        kind: "absolute",
        start_utc: "2021-06-30T01:00:00.000Z",
        end_utc: "2021-06-30T00:00:00.000Z",
      };
      expect(validateWindow(w)).toEqual(["End time must be after start time."]);
    });

    it("should invalidate an absolute window with invalid start time", () => {
      const w: TrendWindow = {
        kind: "absolute",
        start_utc: "invalid",
        end_utc: "2021-06-30T01:00:00.000Z",
      };
      expect(validateWindow(w)).toEqual(["Invalid start time."]);
    });

    it("should invalidate an absolute window with invalid end time", () => {
      const w: TrendWindow = {
        kind: "absolute",
        start_utc: "2021-06-30T00:00:00.000Z",
        end_utc: "invalid",
      };
      expect(validateWindow(w)).toEqual(["Invalid end time."]);
    });
  });
});

