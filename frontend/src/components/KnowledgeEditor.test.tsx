// src/components/KnowledgeEditor.test.tsx
// Unit tests for the knowledge editor: parsing helpers, load/open states, validation and saving.

import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { LoopKnowledge, LoopKnowledgeValues } from "../api";
import { buildUpdate, parseNumberField } from "./KnowledgeEditor";
import { makeLoop } from "../testFixtures";

// ---------------------------------------------------------------------------
// Mocks and helpers
// ---------------------------------------------------------------------------

vi.mock("../api", () => ({
  fetchKnowledge: vi.fn(),
  saveKnowledge: vi.fn(),
}));

import { fetchKnowledge, saveKnowledge } from "../api";
import { KnowledgeEditor } from "./KnowledgeEditor";

/**
 * Fake translator: returns the key plus stringified params so a test can assert
 * an exact string such as `knowledge.rangeOut{"range":"0 – 100"}`.
 */
const t = (key: string, params?: Record<string, string | number>) =>
  key + (params ? JSON.stringify(params) : "");

/** An empty knowledge record: every numeric value "not given", self-regulating. */
const EMPTY_VALUES: LoopKnowledgeValues = {
  delay_s: null,
  ultimate_period_s: null,
  amplitude_limit: null,
  process_kind: "self_regulating",
  pv_eng_min: null,
  pv_eng_max: null,
  out_eng_min: null,
  out_eng_max: null,
};

/** A draft with every text blank; tests override the fields they are about. */
const BLANK_DRAFT = {
  delay_s: "",
  ultimate_period_s: "",
  amplitude_limit: "",
  pv_eng_min: "",
  pv_eng_max: "",
  out_eng_min: "",
  out_eng_max: "",
  process_kind: "self_regulating" as const,
};

/** Builds a knowledge payload; pass overrides for the parts a test is about. */
function makeKnowledge(overrides: Partial<LoopKnowledge> = {}): LoopKnowledge {
  return {
    loop: "Loop A",
    knowledge: EMPTY_VALUES,
    saved: false,
    ranges: { pv: [0, 100], out: [0, 100] },
    pv_eng_default: { min: 0, max: 100 },
    out_eng_default: { min: null, max: null },
    ...overrides,
  };
}

/** Renders the editor with mocked defaults; `overrides` tweaks the loop summary. */
function renderEditor(overrides: Parameters<typeof makeLoop>[0] = {}) {
  return render(
    <KnowledgeEditor
      datasetId="ds-1"
      loop={makeLoop({ name: "Loop A", ...overrides })}
      t={t}
      onSaved={vi.fn()}
    />,
  );
}

// ---------------------------------------------------------------------------
// parseNumberField
// ---------------------------------------------------------------------------

describe("parseNumberField", () => {
  it("returns null for a blank text", () => {
    expect(parseNumberField("   ")).toBeNull();
  });

  it("accepts a decimal comma", () => {
    expect(parseNumberField("1,5")).toBe(1.5);
  });

  it("accepts a decimal point", () => {
    expect(parseNumberField("2.5")).toBe(2.5);
  });

  it("returns invalid for text, zero, a negative and an overflow", () => {
    expect(parseNumberField("abc")).toBe("invalid");
    expect(parseNumberField("0")).toBe("invalid");
    expect(parseNumberField("-1")).toBe("invalid");
    expect(parseNumberField("1e999")).toBe("invalid");
  });
});

// ---------------------------------------------------------------------------
// buildUpdate
// ---------------------------------------------------------------------------

describe("buildUpdate", () => {
  const loaded: LoopKnowledgeValues = {
    ...EMPTY_VALUES,
    delay_s: 10,
    ultimate_period_s: 60,
    amplitude_limit: 5,
  };
  const same = { ...BLANK_DRAFT, delay_s: "10", ultimate_period_s: "60", amplitude_limit: "5" };

  it("keeps only the fields that differ from the loaded values", () => {
    const update = buildUpdate(loaded, { ...same, delay_s: "10", ultimate_period_s: "90", amplitude_limit: "5", process_kind: "self_regulating" });
    expect(update).toEqual({ ultimate_period_s: 90 });
  });

  it("sends null when a numeric field is cleared", () => {
    const update = buildUpdate(loaded, { ...same, delay_s: "", ultimate_period_s: "60", amplitude_limit: "5", process_kind: "self_regulating" });
    expect(update).toEqual({ delay_s: null });
  });

  it("includes a changed process kind", () => {
    const update = buildUpdate(loaded, { ...same, delay_s: "10", ultimate_period_s: "60", amplitude_limit: "5", process_kind: "integrating" });
    expect(update).toEqual({ process_kind: "integrating" });
  });
});

// ---------------------------------------------------------------------------
// Loading and open state
// ---------------------------------------------------------------------------

describe("KnowledgeEditor loading", () => {
  it("shows the loading text while the knowledge is being fetched", () => {
    vi.mocked(fetchKnowledge).mockReturnValue(new Promise(() => {}));

    renderEditor();

    expect(screen.getByText("knowledge.loading")).toBeInTheDocument();
  });

  it("shows the loaded values in the inputs once fetched", async () => {
    vi.mocked(fetchKnowledge).mockResolvedValue(
      makeKnowledge({ knowledge: { ...EMPTY_VALUES, delay_s: 12.5 } }),
    );

    renderEditor();

    await waitFor(() =>
      expect(screen.getByLabelText("knowledge.delay")).toHaveValue("12.5"),
    );
  });
});

describe("KnowledgeEditor open state", () => {
  it("opens the details when some conclusions were not assessed", () => {
    vi.mocked(fetchKnowledge).mockResolvedValue(makeKnowledge());

    const { container } = renderEditor({ not_assessed: ["harris"] });

    expect(container.querySelector("details")).toHaveAttribute("open");
  });

  it("keeps the details closed when every conclusion was assessed", () => {
    vi.mocked(fetchKnowledge).mockResolvedValue(makeKnowledge());

    const { container } = renderEditor({ not_assessed: [] });

    expect(container.querySelector("details")).not.toHaveAttribute("open");
  });
});

// ---------------------------------------------------------------------------
// Validation
// ---------------------------------------------------------------------------

describe("KnowledgeEditor validation", () => {
  it("shows an alert and disables save when a value is invalid", async () => {
    vi.mocked(fetchKnowledge).mockResolvedValue(makeKnowledge());

    renderEditor();
    const delay = await screen.findByLabelText("knowledge.delay");
    const save = screen.getByRole("button", { name: "knowledge.save" });

    fireEvent.change(delay, { target: { value: "abc" } });

    expect(screen.getByRole("alert")).toHaveTextContent("knowledge.invalid");
    expect(save).toBeDisabled();
  });

  it("disables save until something changes", async () => {
    vi.mocked(fetchKnowledge).mockResolvedValue(makeKnowledge());

    renderEditor();

    await screen.findByLabelText("knowledge.delay");
    expect(screen.getByRole("button", { name: "knowledge.save" })).toBeDisabled();

    fireEvent.change(screen.getByLabelText("knowledge.delay"), { target: { value: "3" } });
    expect(screen.getByRole("button", { name: "knowledge.save" })).toBeEnabled();
  });
});

// ---------------------------------------------------------------------------
// Saving
// ---------------------------------------------------------------------------

describe("KnowledgeEditor saving", () => {
  it("saves only the changed fields and reports success", async () => {
    vi.mocked(fetchKnowledge).mockResolvedValue(
      makeKnowledge({ knowledge: { ...EMPTY_VALUES, delay_s: 10 } }),
    );
    vi.mocked(saveKnowledge).mockResolvedValue(
      makeKnowledge({ knowledge: { ...EMPTY_VALUES, delay_s: 10, ultimate_period_s: 60 } }),
    );
    const onSaved = vi.fn();
    render(
      <KnowledgeEditor
        datasetId="ds-1"
        loop={makeLoop({ name: "Loop A" })}
        t={t}
        onSaved={onSaved}
      />,
    );

    fireEvent.change(await screen.findByLabelText("knowledge.ultimate"), {
      target: { value: "60" },
    });
    fireEvent.click(screen.getByRole("button", { name: "knowledge.save" }));

    await waitFor(() => expect(saveKnowledge).toHaveBeenCalledTimes(1));
    expect(saveKnowledge).toHaveBeenCalledWith("ds-1", "Loop A", { ultimate_period_s: 60 });
    expect(onSaved).toHaveBeenCalledOnce();
    expect(screen.getByText("knowledge.saved")).toBeInTheDocument();
  });

  it("shows the error alert and does not call onSaved when the save fails", async () => {
    vi.mocked(fetchKnowledge).mockResolvedValue(makeKnowledge());
    vi.mocked(saveKnowledge).mockRejectedValue(new Error("boom"));
    const onSaved = vi.fn();
    render(
      <KnowledgeEditor
        datasetId="ds-1"
        loop={makeLoop({ name: "Loop A" })}
        t={t}
        onSaved={onSaved}
      />,
    );

    fireEvent.change(await screen.findByLabelText("knowledge.delay"), { target: { value: "3" } });
    fireEvent.click(screen.getByRole("button", { name: "knowledge.save" }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent('knowledge.error{"reason":"Error: boom"}');
    expect(onSaved).not.toHaveBeenCalled();
  });

  it("restores the loaded values when reset is clicked", async () => {
    vi.mocked(fetchKnowledge).mockResolvedValue(
      makeKnowledge({ knowledge: { ...EMPTY_VALUES, delay_s: 10 } }),
    );

    renderEditor();
    const delay = await screen.findByLabelText("knowledge.delay");
    fireEvent.change(delay, { target: { value: "99" } });

    fireEvent.click(screen.getByRole("button", { name: "knowledge.reset" }));

    expect(delay).toHaveValue("10");
  });
});

// ---------------------------------------------------------------------------
// Range info and load errors
// ---------------------------------------------------------------------------

describe("KnowledgeEditor range info", () => {
  it("shows the configured output range", async () => {
    vi.mocked(fetchKnowledge).mockResolvedValue(makeKnowledge({ ranges: { pv: null, out: [0, 100] } }));

    renderEditor();
    const form = await screen.findByLabelText("knowledge.delay").then((input) =>
      input.closest("form") as HTMLElement,
    );

    expect(within(form).getByText('knowledge.rangeOut{"range":"0 – 100"}')).toBeInTheDocument();
  });

  it("warns when the output range is not configured", async () => {
    vi.mocked(fetchKnowledge).mockResolvedValue(makeKnowledge({ ranges: { pv: [0, 100], out: null } }));

    renderEditor();
    const form = await screen.findByLabelText("knowledge.delay").then((input) =>
      input.closest("form") as HTMLElement,
    );

    expect(within(form).getByText("knowledge.rangeOutMissing")).toBeInTheDocument();
  });
});

describe("KnowledgeEditor load error", () => {
  it("shows the error text when the knowledge cannot be loaded", async () => {
    vi.mocked(fetchKnowledge).mockRejectedValue(new Error("offline"));

    renderEditor();

    await waitFor(() =>
      expect(screen.getByText('knowledge.error{"reason":"Error: offline"}')).toBeInTheDocument(),
    );
  });
});

// ---------------------------------------------------------------------------
// Measurement ranges, precedence hint and the save diff
// ---------------------------------------------------------------------------

describe("KnowledgeEditor ranges", () => {
  it("accepts a negative range and saves it with a decimal comma", async () => {
    vi.mocked(fetchKnowledge).mockResolvedValue(makeKnowledge());
    vi.mocked(saveKnowledge).mockResolvedValue(
      makeKnowledge({ knowledge: { ...EMPTY_VALUES, pv_eng_min: -50.5, pv_eng_max: 0 } }),
    );
    renderEditor();

    fireEvent.change(await screen.findByLabelText("knowledge.pvMin"), { target: { value: "-50,5" } });
    fireEvent.change(screen.getByLabelText("knowledge.pvMax"), { target: { value: "0" } });
    fireEvent.click(screen.getByRole("button", { name: "knowledge.save" }));

    await waitFor(() => expect(saveKnowledge).toHaveBeenCalledWith("ds-1", "Loop A", { pv_eng_min: -50.5, pv_eng_max: 0 }));
  });

  it("blocks save and alerts when the minimum is not below the maximum", async () => {
    vi.mocked(fetchKnowledge).mockResolvedValue(makeKnowledge());
    renderEditor();

    fireEvent.change(await screen.findByLabelText("knowledge.outMin"), { target: { value: "10" } });
    fireEvent.change(screen.getByLabelText("knowledge.outMax"), { target: { value: "10" } });

    expect(screen.getByRole("alert")).toHaveTextContent("knowledge.rangeInverted");
    expect(screen.getByRole("button", { name: "knowledge.save" })).toBeDisabled();
  });

  it("states the precedence and shows the tag default as placeholder", async () => {
    vi.mocked(fetchKnowledge).mockResolvedValue(makeKnowledge());
    renderEditor();

    const input = await screen.findByLabelText("knowledge.pvMin");

    expect(screen.getByText("knowledge.rangesPrecedence")).toBeInTheDocument();
    expect(input).toHaveAttribute("placeholder", 'knowledge.tagDefault{"value":0}');
  });
});

describe("KnowledgeEditor process kind help", () => {
  it("explains integrating versus self-regulating with a level example", async () => {
    vi.mocked(fetchKnowledge).mockResolvedValue(makeKnowledge());
    renderEditor();

    const select = await screen.findByLabelText("knowledge.processKind");

    expect(select).toHaveAccessibleDescription("knowledge.kindHelp");
    expect(screen.getByText("knowledge.kindExampleTitle")).toBeInTheDocument();
    expect(screen.getByText("knowledge.kindExample")).toBeInTheDocument();
  });
});

describe("KnowledgeEditor save diff", () => {
  it("lists old and new values, shows cleared, and can be dismissed", async () => {
    vi.mocked(fetchKnowledge).mockResolvedValue(
      makeKnowledge({ knowledge: { ...EMPTY_VALUES, delay_s: 10, out_eng_max: 80 } }),
    );
    vi.mocked(saveKnowledge).mockResolvedValue(
      makeKnowledge({ knowledge: { ...EMPTY_VALUES, delay_s: 12 } }),
    );
    renderEditor();

    fireEvent.change(await screen.findByLabelText("knowledge.delay"), { target: { value: "12" } });
    fireEvent.change(screen.getByLabelText("knowledge.outMax"), { target: { value: "" } });
    fireEvent.click(screen.getByRole("button", { name: "knowledge.save" }));

    const items = await screen.findAllByRole("listitem");
    expect(items[0]).toHaveTextContent("knowledge.delay{\"unit\":");
    expect(items[0]).toHaveTextContent("10 -> 12");
    expect(items[1]).toHaveTextContent("80 -> knowledge.cleared");
    fireEvent.click(screen.getByRole("button", { name: "knowledge.dismiss" }));
    expect(screen.queryAllByRole("listitem")).toHaveLength(0);
  });
});
