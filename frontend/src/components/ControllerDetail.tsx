// frontend/src/components/ControllerDetail.tsx
/**
 * Detail panel of one controller: state, the On / Standby / Off buttons (only with
 * ctl.operate; Off is always enabled, it never waits for anything) and the variable table.
 */

import type { ControllerCommand, ControllerDetail as Detail, VariableOverride } from "../controllersApi";
import type { Translate } from "../findings";
import { ControllerVariableRow } from "./ControllerVariableRow";
import { reasonText, stateLevel } from "./controllersFormat";
import { StatusChip } from "./StatusChip";

export interface ControllerDetailProps {
  detail: Detail;
  canOperate: boolean;
  onCommand: (command: ControllerCommand) => void;
  onSave: (variableId: string, override: VariableOverride) => void;
  t: Translate;
}

const COMMANDS: { command: ControllerCommand; label: string; testId: string }[] = [
  { command: "switch_on", label: "controllers.on", testId: "controller-on" },
  { command: "standby", label: "controllers.standby", testId: "controller-standby" },
  { command: "switch_off", label: "controllers.off", testId: "controller-off" },
];

function CommandButtons({ onCommand, t }: Pick<ControllerDetailProps, "onCommand" | "t">) {
  return (
    <div className="toolbar" role="group" aria-label={t("controllers.commands")} data-testid="controller-commands">
      {COMMANDS.map(({ command, label, testId }) => (
        <button key={command} type="button" className="filter-chip" data-testid={testId} onClick={() => onCommand(command)}>
          {t(label)}
        </button>
      ))}
    </div>
  );
}

function rowKey(variable: Detail["variables"][number]): string {
  const { operator } = variable.limits;
  return `${variable.id}:${operator?.lo}:${operator?.hi}:${variable.enabled}`;
}

export function ControllerDetail({ detail, canOperate, onCommand, onSave, t }: ControllerDetailProps) {
  return (
    <section className="notice" data-testid="controllers-detail" aria-labelledby="controller-detail-title">
      <h2 id="controller-detail-title">{detail.id}</h2>
      <p>
        <StatusChip level={stateLevel(detail.state)} label={t(`controllers.state.${detail.state}`)} />{" "}
        <span className="hint">{reasonText(t, detail.reason)}</span>
      </p>
      {detail.description && <p className="hint">{detail.description}</p>}
      {canOperate && <CommandButtons onCommand={onCommand} t={t} />}
      <div className="table-scroll">
        <table className="loops-table" data-testid="controller-variables">
          <caption className="hint">{t("controllers.variables")}</caption>
          <thead>
            <tr>
              <th scope="col">{t("controllers.col.variable")}</th>
              <th scope="col">{t("controllers.col.role")}</th>
              <th scope="col">{t("controllers.col.status")}</th>
              <th scope="col">{t("controllers.col.value")}</th>
              <th scope="col">{t("controllers.col.eng")}</th>
              <th scope="col">{t("controllers.col.operator")}</th>
              <th scope="col">{t("controllers.col.enabled")}</th>
            </tr>
          </thead>
          <tbody>
            {detail.variables.map((variable) => (
              <ControllerVariableRow key={rowKey(variable)} variable={variable} canOperate={canOperate} onSave={onSave} t={t} />
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
