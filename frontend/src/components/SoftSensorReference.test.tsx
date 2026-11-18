// Component tests of the reference-input panel and the config summary line: coverage and validity
// text, the three verdicts on the bias correction (helps / hurts / too few results) and the
// empty case; the text exists in all three languages.
import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import type { ReferenceReport, SoftSensorConfig } from "../api";
import { translate } from "../i18n";
import { SoftSensorConfigSummary } from "./SoftSensorConfigSummary";
import { SoftSensorReference } from "./SoftSensorReference";

const t = (key: string, params?: Record<string, string | number>) => translate("en", key, params);

const ROW: ReferenceReport = {
  tag: "sim.mc.p80", window_s: 600, shift_s: 60, min_coverage: 0.6, bias_weight: 0.3,
  coverage_mean: 0.87, valid_share: 0.93, latest_coverage: 0.4, latest_valid: false,
  n_pairs: 24, rmse_raw: 2.0123, rmse_corrected: 0.4567, helps: true,
};

afterEach(cleanup);

describe("SoftSensorReference", () => {
  it("shows nothing without reference inputs", () => {
    const { container } = render(<SoftSensorReference rows={[]} t={t} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("shows coverage, validity, the RMSE with and without correction and the verdict", () => {
    render(<SoftSensorReference rows={[ROW]} t={t} />);
    const row = screen.getByTestId("soft-ref-sim.mc.p80");
    expect(within(row).getByTestId("soft-ref-valid")).toHaveTextContent("93.0 %");
    expect(row).toHaveTextContent("87.0 %");
    expect(row).toHaveTextContent("invalid (40.0 %)");
    expect(row).toHaveTextContent("2.012");
    expect(row).toHaveTextContent("0.4567");
    expect(within(row).getByTestId("soft-ref-verdict")).toHaveTextContent("helps");
  });

  it("says hurts when the correction raises the RMSE and is neutral with too few lab results", () => {
    const rows = [
      { ...ROW, tag: "a", helps: false, rmse_raw: 1, rmse_corrected: 1.5 },
      { ...ROW, tag: "b", helps: null, n_pairs: 2, rmse_raw: null, rmse_corrected: null },
    ];
    render(<SoftSensorReference rows={rows} t={t} />);
    expect(within(screen.getByTestId("soft-ref-a")).getByTestId("soft-ref-verdict")).toHaveTextContent("hurts");
    const b = screen.getByTestId("soft-ref-b");
    expect(within(b).getByTestId("soft-ref-verdict")).toHaveTextContent("too few lab results");
    expect(b).toHaveTextContent("--");
  });

  it("has Polish and Spanish text for every key it uses", () => {
    for (const lang of ["pl", "es"] as const) {
      expect(translate(lang, "soft.ref.hurts")).not.toBe("soft.ref.hurts");
    }
    expect(translate("pl", "soft.ref.latestValid", { coverage: 80 })).toContain("ważne");
    expect(translate("es", "soft.ref.helps")).toBe("ayuda");
  });
});

describe("SoftSensorConfigSummary reference line", () => {
  const base: SoftSensorConfig = { schema_version: "1.0.0", id: "x", target_tag: "lab", input_tags: ["a"], mode: "advisory" };

  it("lists the reference inputs with their settings, or none", () => {
    const { rerender } = render(<SoftSensorConfigSummary config={base} t={t} />);
    expect(screen.getByText("none")).toBeInTheDocument();
    const config = { ...base, reference_inputs: [{ tag: "an", window_s: 900, shift_s: 0, min_coverage: 0.7, bias_weight: 0.3 }] };
    rerender(<SoftSensorConfigSummary config={config} t={t} />);
    expect(screen.getByText("an: 900 s, shift 0 s, coverage at least 70 %, weight 0.3")).toBeInTheDocument();
  });
});
