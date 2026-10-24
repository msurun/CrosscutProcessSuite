// Tests of the unreliable-input warning of the Anomalies scan: nothing without tags, and the
// tags listed largest share first with their rounded percentages.
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { translate } from "../i18n";
import { AnomalyRamp } from "./AnomalyRamp";

const t = (key: string, params?: Record<string, string | number>) => translate("en", key, params);

afterEach(() => cleanup());

describe("AnomalyRamp", () => {
  it("renders nothing without unreliable tags", () => {
    const { container } = render(<AnomalyRamp tags={undefined} t={t} />);
    expect(container.innerHTML).toBe("");
    const { container: empty } = render(<AnomalyRamp tags={{}} t={t} />);
    expect(empty.innerHTML).toBe("");
    expect(screen.queryByTestId("anomaly-ramp")).toBeNull();
  });

  it("renders the tags sorted by share with percentages", () => {
    render(<AnomalyRamp tags={{ tag_b: 0.5, tag_a: 0.9 }} t={t} />);
    const line = screen.getByTestId("anomaly-ramp");
    expect(line.className).toContain("status-warning");
    expect(line.textContent).toContain("tag_a (90 %), tag_b (50 %)");
  });
});
