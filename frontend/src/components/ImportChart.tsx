// Chart of the checked record for the Import view: the process variable and the controller output
// over minutes from the start of the record, in two panes that share the cursor.
import type { IntakeCheck } from "../api";
import type { Translate } from "../findings";
import { sampleColumns } from "../intake";
import { TrendPane } from "./TrendPane";

const PANE_HEIGHT_PX = 150;

/** PV pane above OUT pane; nothing when the sample is empty. */
export function ImportChart({ check, t }: { check: IntakeCheck; t: Translate }) {
  const { minutes, pv, out } = sampleColumns(check);
  if (minutes.length === 0) return null;
  const common = { height: PANE_HEIGHT_PX, syncKey: "import", xIsTime: false, xLabel: t("import.chart.axis"), t } as const;
  return (
    <div data-testid="import-chart">
      <figure className="anomaly-chart">
        <figcaption>{t("import.chart.pv")}</figcaption>
        <TrendPane data={[minutes, pv]} labels={[t("import.chart.pv")]} colors={["--series-1"]} roles={["pv"]} {...common} />
      </figure>
      <figure className="anomaly-chart">
        <figcaption>{t("import.chart.out")}</figcaption>
        <TrendPane data={[minutes, out]} labels={[t("import.chart.out")]} colors={["--series-2"]} roles={["out"]} {...common} />
      </figure>
    </div>
  );
}
