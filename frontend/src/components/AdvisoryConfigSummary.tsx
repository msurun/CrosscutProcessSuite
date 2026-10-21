// Read-only summary of a supervisor configuration: target loop, thresholds, gates and the mode,
// which is shown as "advisory only" (the schema allows no other active mode).
import type { Translate } from "../findings";
import type { SupervisorConfig } from "../api";

/** One gate as a sentence: which loop states block, which only degrade. */
function gateText(gate: SupervisorConfig["gates"][number], t: Translate): string {
  const name = (code: string) => t(`advisory.loopState.${code}`);
  const parts = [gate.loop];
  if (gate.block_on !== undefined && gate.block_on.length > 0) {
    parts.push(t("advisory.config.blocksOn", { states: gate.block_on.map(name).join(", ") }));
  }
  if (gate.warn_on !== undefined && gate.warn_on.length > 0) {
    parts.push(t("advisory.config.warnsOn", { states: gate.warn_on.map(name).join(", ") }));
  }
  return parts.join(": ");
}

/** The configuration as a definition list. */
export function AdvisoryConfigSummary({ config, t }: { config: SupervisorConfig; t: Translate }) {
  const [low, high] = config.display_clamp;
  const rows: [string, string][] = [
    [t("advisory.config.mode"), config.mode === "advisory" ? t("advisory.mode.advisory") : t("advisory.mode.off")],
    [t("advisory.config.targetLoop"), config.target_loop],
    [t("advisory.config.rulebase"), `${config.fuzzy_system_id} → ${config.output_id}`],
    [t("advisory.config.silentBand"), String(config.silent_band)],
    [t("advisory.config.minActivation"), String(config.min_activation)],
    [t("advisory.config.minInterval"), t("advisory.config.seconds", { value: config.min_interval_s })],
    [t("advisory.config.clamp"), `${low} … ${high}`],
  ];
  return (
    <section aria-label={t("advisory.config.title")}>
      <h3>{t("advisory.config.title")}</h3>
      {config.description !== undefined && <p className="hint">{config.description}</p>}
      <dl className="advisory-config">
        {rows.map(([label, value]) => (
          <div key={label}>
            <dt>{label}</dt>
            <dd>{value}</dd>
          </div>
        ))}
        <div>
          <dt>{t("advisory.config.gates")}</dt>
          <dd>
            {config.gates.length === 0 ? t("advisory.config.noGates") : (
              <ul>
                {config.gates.map((gate) => <li key={gate.loop}>{gateText(gate, t)}</li>)}
              </ul>
            )}
          </dd>
        </div>
      </dl>
    </section>
  );
}
