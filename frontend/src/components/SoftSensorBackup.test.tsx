// Component tests of the backup panel: nothing without backup mode, the status chip for both
// sources, the quality line, the switch history rows and the empty history; all three languages.
import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import type { SoftSensorBackup as Backup } from "../api";
import { translate } from "../i18n";
import { SoftSensorBackup } from "./SoftSensorBackup";

const BACKUP: Backup = {
  measured_tag: "an.p80",
  series: { t_s: [0, 60], output: [1, 2], substituted: [false, true], quality: [0, 1] },
  switches: [
    { t_s: 3600, from: "measured", to: "backup", reason: "frozen" },
    { t_s: 7200, from: "backup", to: "measured", reason: "measurement_valid" },
  ],
  n_substituted: 60,
  latest: { substituted: true, quality: 1, reason: "frozen" },
};

afterEach(cleanup);

describe("SoftSensorBackup", () => {
  it("shows nothing when backup mode is off", () => {
    const { container } = render(<SoftSensorBackup backup={null} t={(k) => k} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("shows the substitution chip, quality code, count and switch history", () => {
    render(<SoftSensorBackup backup={BACKUP} t={(k, p) => translate("en", k, p)} />);
    expect(screen.getByTestId("soft-backup-status")).toHaveTextContent("Substituted by the virtual sensor (an.p80 invalid)");
    expect(screen.getByTestId("soft-backup-quality")).toHaveTextContent("Quality code 1: substituted; latest reason: frozen value");
    expect(screen.getByTestId("soft-backup-count")).toHaveTextContent("60");
    const rows = within(screen.getByTestId("soft-backup-switches")).getAllByRole("row");
    expect(rows).toHaveLength(3);
    expect(rows[1]).toHaveTextContent("1.00 hmeasurementvirtual sensorfrozen value");
    expect(rows[2]).toHaveTextContent("2.00 hvirtual sensormeasurementmeasurement valid again");
  });

  it("shows the measured chip and an empty history", () => {
    const measured = { ...BACKUP, switches: [], latest: { substituted: false, quality: 0, reason: "" } };
    render(<SoftSensorBackup backup={measured} t={(k, p) => translate("pl", k, p)} />);
    expect(screen.getByTestId("soft-backup-status")).toHaveTextContent("Używana wartość zmierzona (an.p80)");
    expect(screen.getByTestId("soft-backup-none")).toHaveTextContent("Brak przełączeń");
  });
});
