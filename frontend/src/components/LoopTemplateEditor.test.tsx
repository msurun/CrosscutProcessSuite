// src/components/LoopTemplateEditor.test.tsx
// Behaviour tests of the loop template editor: loading the library, switching templates,
// editing a field, saving a site copy, refusing an impossible range and a failed load.

import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { LoopTemplate } from "../loopTemplate";
import { LoopTemplateEditor } from "./LoopTemplateEditor";

/** Fake translator: the key itself. */
const t = (key: string) => key;

/** A small valid template; `overrides` tweak what a test is about. */
function makeTemplate(overrides: Partial<LoopTemplate> = {}): LoopTemplate {
  return {
    key: "flow",
    label: "Flow",
    description: "Fast and tight",
    process_kind: "self_regulating",
    dynamics: {
      gain_min: 0.5,
      gain_max: 5,
      time_constant_s_min: 5,
      time_constant_s_max: 120,
      dead_time_s_min: 1,
      dead_time_s_max: 30,
    },
    kpi_thresholds: {
      service_factor_min: 0.9,
      saturation_share_max: 0.05,
      oscillation_index_max: 0.3,
      noise_ratio_max: 0.2,
    },
    diagnosis_rules: ["instrument", "valve", "tuning"],
    tuning: { rule: "simc", target_closed_loop_time_constant_ratio: 1, robustness: 0.3 },
    tests: { allowed: ["step"], default_step_pct: 5 },
    origin: "builtin",
    ...overrides,
  };
}

function json(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  fetchMock = vi.fn(async (_url: string, init?: RequestInit) => {
    if (init?.method === "PUT") {
      const body = JSON.parse(String(init.body)) as LoopTemplate;
      return json(200, { ...body, origin: "site" });
    }
    return json(200, {
      templates: [makeTemplate(), makeTemplate({ key: "temperature", label: "Temperature" })],
    });
  });
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

async function openEditor() {
  render(<LoopTemplateEditor t={t} />);
  await screen.findByTestId("loop-template-select");
}

describe("LoopTemplateEditor", () => {
  it("loads the library and shows the first template", async () => {
    await openEditor();
    expect(screen.getByTestId("loop-template-select")).toHaveValue("flow");
    expect(screen.getByTestId("loop-template-key")).toHaveTextContent("flow");
    expect(screen.getByLabelText("loopTemplates.label")).toHaveValue("Flow");
  });

  it("switches the draft when another template is selected", async () => {
    await openEditor();
    fireEvent.change(screen.getByTestId("loop-template-select"), { target: { value: "temperature" } });
    expect(screen.getByLabelText("loopTemplates.label")).toHaveValue("Temperature");
  });

  it("saves an edited site copy without the read-only origin", async () => {
    await openEditor();
    fireEvent.change(screen.getByLabelText("loopTemplates.label"), { target: { value: "Site flow" } });
    fireEvent.click(screen.getByTestId("loop-template-save"));
    await screen.findByText("loopTemplates.saved");
    const [, init] = fetchMock.mock.calls[fetchMock.mock.calls.length - 1] as [string, RequestInit];
    expect(init.method).toBe("PUT");
    expect(JSON.parse(String(init.body))).toMatchObject({ key: "flow", label: "Site flow" });
    expect(JSON.parse(String(init.body))).not.toHaveProperty("origin");
  });

  it("refuses to save an impossible dynamics range", async () => {
    await openEditor();
    fireEvent.change(screen.getByLabelText(/loopTemplates.dynamics.gain \(loopTemplates.dynamics.min\)/), {
      target: { value: "999" },
    });
    expect(screen.getByRole("alert")).toHaveTextContent("loopTemplates.rangeError");
    expect(screen.getByTestId("loop-template-save")).toBeDisabled();
  });

  it("shows a failed load instead of an empty form", async () => {
    fetchMock.mockRejectedValue(new Error("network down"));
    render(<LoopTemplateEditor t={t} />);
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("loopTemplates.loadError"));
    expect(screen.queryByTestId("loop-template-select")).not.toBeInTheDocument();
  });
});
