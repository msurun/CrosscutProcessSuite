// Component tests of the bias correction line in the soft sensor config summary (#159): schema
// defaults when the block is absent, configured values, the caveat text and its Polish/Spanish text.
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import type { SoftSensorConfig } from "../api";
import { translate } from "../i18n";
import { SoftSensorConfigSummary } from "./SoftSensorConfigSummary";

const t = (key: string, params?: Record<string, string | number>) => translate("en", key, params);
const base: SoftSensorConfig = { schema_version: "1.0.0", id: "x", target_tag: "lab", input_tags: ["a"], mode: "advisory" };

afterEach(cleanup);

describe("SoftSensorConfigSummary bias correction", () => {
  it("shows the documented defaults when the block is absent", () => {
    render(<SoftSensorConfigSummary config={base} t={t} />);
    expect(screen.getByText("EWMA weight 0.3, limit 3 sigma, drift after 3 in a row")).toBeInTheDocument();
  });

  it("shows configured values", () => {
    const config = { ...base, bias_correction: { weight: 0.5, k_sigma: 2.5, consecutive: 4 } };
    render(<SoftSensorConfigSummary config={config} t={t} />);
    expect(screen.getByText("EWMA weight 0.5, limit 2.5 sigma, drift after 4 in a row")).toBeInTheDocument();
  });

  it("says the correction compensates drift and does not prove skill", () => {
    render(<SoftSensorConfigSummary config={base} t={t} />);
    expect(screen.getByTestId("soft-bias-hint")).toHaveTextContent("does not prove that the model beats lab persistence");
  });

  it("has Polish and Spanish text for every new key", () => {
    for (const lang of ["pl", "es"] as const) {
      for (const key of ["schema.softsensor.bias_correction", "soft.config.biasCorrection", "soft.config.biasCorrectionItem", "soft.config.biasCorrectionHint"]) {
        expect(translate(lang, key)).not.toBe(key);
      }
    }
  });
});
