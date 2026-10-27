// src/components/SettingsTables.test.tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { DcsForms, PiSettingsTable, VendorBlock, formatNumber } from "./SettingsTables";

// The components take a translator function; tests only need the key back.
const t = (key: string) => key;

describe("formatNumber", () => {
  it("keeps four significant digits for a number below one hundred", () => {
    expect(formatNumber(23.879239)).toBe("23.88");
  });

  it("keeps four significant digits for a small decimal", () => {
    expect(formatNumber(0.0659783)).toBe("0.06598");
  });

  it("shows an integer above one thousand without decimals", () => {
    expect(formatNumber(1200)).toBe("1200");
  });

  it("shows zero as a plain zero", () => {
    expect(formatNumber(0)).toBe("0");
  });
});

describe("PiSettingsTable", () => {
  const settings = {
    simc: { kc: 0.7743, ti_s: 49.48 },
    amigo: { kc: 0.8728, ti_s: 30.21 },
  };

  it("renders the translated column headers", () => {
    render(<PiSettingsTable settings={settings} t={t} />);

    expect(screen.getByText("tuning.settings.rule")).toBeInTheDocument();
    expect(screen.getByText("tuning.settings.kc")).toBeInTheDocument();
    expect(screen.getByText("tuning.settings.ti")).toBeInTheDocument();
  });

  it("renders the SIMC row with formatted gains", () => {
    render(<PiSettingsTable settings={settings} t={t} />);

    const row = screen.getByRole("row", { name: /SIMC/ });

    expect(row).toHaveTextContent("0.7743");
    expect(row).toHaveTextContent("49.48");
  });

  it("renders the AMIGO row with formatted gains", () => {
    render(<PiSettingsTable settings={settings} t={t} />);

    const row = screen.getByRole("row", { name: /AMIGO/ });

    expect(row).toHaveTextContent("0.8728");
    expect(row).toHaveTextContent("30.21");
  });
});

describe("DcsForms", () => {
  it("renders a heading per form with its formatted values", () => {
    const forms = {
      reactor: { gain: 12.3456 },
      feeder: { gain: 1.5 },
    };

    render(<DcsForms forms={forms} t={t} />);

    expect(screen.getByRole("heading", { name: "tuning.dcs.reactor" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "tuning.dcs.feeder" })).toBeInTheDocument();
  });

  it("renders the raw key as the term and the formatted value as the description", () => {
    const forms = { reactor: { gain: 12.3456 } };

    render(<DcsForms forms={forms} t={t} />);

    expect(screen.getByText("gain")).toBeInTheDocument();
    expect(screen.getByText("12.35")).toBeInTheDocument();
  });

  it("renders nothing when there are no forms", () => {
    const { container } = render(<DcsForms forms={{}} t={t} />);

    expect(container).toBeEmptyDOMElement();
  });
});

describe("VendorBlock", () => {
  const vendorForms = {
    abb_pidcc: {
      block: "PidCC",
      evidence: "partly_verified" as const,
      source: "s",
      tags: { Gain: 1.5, TI: 30 },
      caveats: ["check units"],
    },
  };

  it("renders nothing when the loop has no vendor", () => {
    const { container } = render(<VendorBlock payload={{ vendor: null, vendor_forms: vendorForms }} t={t} />);

    expect(container).toBeEmptyDOMElement();
  });

  it("renders nothing when the payload has no vendor block", () => {
    const { container } = render(<VendorBlock payload={{}} t={t} />);

    expect(container).toBeEmptyDOMElement();
  });

  it("renders the parameter names, values and caveats of the vendor block", () => {
    render(<VendorBlock payload={{ vendor: "abb_pidcc", vendor_forms: vendorForms }} t={t} />);

    expect(screen.getByText("Gain")).toBeInTheDocument();
    expect(screen.getByText("TI")).toBeInTheDocument();
    expect(screen.getByText("1.5")).toBeInTheDocument();
    expect(screen.getByText("check units")).toBeInTheDocument();
  });
});
