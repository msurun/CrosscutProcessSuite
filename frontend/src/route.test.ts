// Behaviour tests for the hash-router core: parsing, formatting and the with* helpers.

import { describe, expect, it } from "vitest";
import {
  DEFAULT_ROUTE,
  formatHash,
  parseHash,
  withDataset,
  withLoop,
  withView,
  type Route,
} from "./route";

describe("parseHash", () => {
  it("returns the default route for an empty hash", () => {
    expect(parseHash("")).toEqual(DEFAULT_ROUTE);
  });

  it("returns the default route for a bare hash", () => {
    expect(parseHash("#")).toEqual(DEFAULT_ROUTE);
  });

  it("returns the default route for a lone slash", () => {
    expect(parseHash("#/")).toEqual(DEFAULT_ROUTE);
  });

  it("returns the default route for an unknown view", () => {
    expect(parseHash("#/d/sales/bogus")).toEqual(DEFAULT_ROUTE);
  });

  it("returns the default route for too many segments", () => {
    expect(parseHash("#/d/sales/loops/one/detail/extra")).toEqual(DEFAULT_ROUTE);
  });

  it("returns the default route for bad percent-encoding", () => {
    expect(parseHash("#/d/%E0%A4%A/trends")).toEqual(DEFAULT_ROUTE);
  });

  it("parses a dataset and a view", () => {
    expect(parseHash("#/d/sales/trends")).toEqual({
      dataset: "sales",
      view: "trends",
      loop: null,
      sub: "detail",
    });
  });

  it("parses a loop without a sub, defaulting sub to detail", () => {
    expect(parseHash("#/d/sales/loops/checkout")).toEqual({
      dataset: "sales",
      view: "loops",
      loop: "checkout",
      sub: "detail",
    });
  });

  it("parses a loop with an explicit sub", () => {
    expect(parseHash("#/d/sales/loops/checkout/tuning")).toEqual({
      dataset: "sales",
      view: "loops",
      loop: "checkout",
      sub: "tuning",
    });
  });

  it("falls back to detail when the sub is unknown", () => {
    expect(parseHash("#/d/sales/loops/checkout/bogus").sub).toBe("detail");
  });

  it("drops a loop segment given on a non-loops view", () => {
    expect(parseHash("#/d/sales/trends/checkout")).toEqual({
      dataset: "sales",
      view: "trends",
      loop: null,
      sub: "detail",
    });
  });
});

describe("formatHash", () => {
  it("formats the default route", () => {
    expect(formatHash(DEFAULT_ROUTE)).toBe("#/d//trends");
  });

  it("formats a loops route with a sub", () => {
    const route: Route = { dataset: "sales", view: "loops", loop: "checkout", sub: "benefit" };
    expect(formatHash(route)).toBe("#/d/sales/loops/checkout/benefit");
  });

  it("encodes awkward characters in a dataset name", () => {
    const route: Route = { dataset: "a/b#c d", view: "trends", loop: null, sub: "detail" };
    expect(formatHash(route)).toBe("#/d/a%2Fb%23c%20d/trends");
  });

  it("omits the loop when it is null", () => {
    const route: Route = { dataset: "sales", view: "loops", loop: null, sub: "detail" };
    expect(formatHash(route)).toBe("#/d/sales/loops");
  });
});

describe("round trip", () => {
  const awkwardRoutes: Route[] = [
    { dataset: "sales", view: "trends", loop: null, sub: "detail" },
    { dataset: "a/b", view: "fuzzy", loop: null, sub: "detail" },
    { dataset: "#hash?q=1", view: "trends", loop: null, sub: "detail" },
    { dataset: "with space", view: "loops", loop: "my loop", sub: "detail" },
    { dataset: "100%", view: "loops", loop: "a/b#c?d", sub: "benefit" },
    { dataset: "Pętla", view: "loops", loop: "Über", sub: "tuning" },
    { dataset: "", view: "loops", loop: null, sub: "detail" },
  ];

  it.each(awkwardRoutes)("survives $dataset / $loop (%#)", (route) => {
    expect(parseHash(formatHash(route))).toEqual(route);
  });
});

describe("withDataset", () => {
  it("switches the dataset and resets loop and sub", () => {
    const start: Route = { dataset: "sales", view: "loops", loop: "checkout", sub: "tuning" };
    expect(withDataset(start, "billing")).toEqual({
      dataset: "billing",
      view: "loops",
      loop: null,
      sub: "detail",
    });
  });
});

describe("withView", () => {
  it("drops loop and sub when leaving the loops view", () => {
    const start: Route = { dataset: "sales", view: "loops", loop: "checkout", sub: "tuning" };
    expect(withView(start, "trends")).toEqual({
      dataset: "sales",
      view: "trends",
      loop: null,
      sub: "detail",
    });
  });

  it("keeps the loop when switching to the loops view", () => {
    const start: Route = { dataset: "sales", view: "loops", loop: "checkout", sub: "tuning" };
    expect(withView(start, "loops")).toEqual(start);
  });
});

describe("withLoop", () => {
  it("forces the loops view and sets the loop", () => {
    const start: Route = { dataset: "sales", view: "trends", loop: null, sub: "detail" };
    expect(withLoop(start, "checkout")).toEqual({
      dataset: "sales",
      view: "loops",
      loop: "checkout",
      sub: "detail",
    });
  });

  it("uses the given sub", () => {
    const start: Route = { dataset: "sales", view: "trends", loop: null, sub: "detail" };
    expect(withLoop(start, "checkout", "benefit").sub).toBe("benefit");
  });

  it("clears the loop when given null", () => {
    const start: Route = { dataset: "sales", view: "loops", loop: "checkout", sub: "tuning" };
    expect(withLoop(start, null).loop).toBeNull();
  });
});
