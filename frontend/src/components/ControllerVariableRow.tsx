// frontend/src/components/ControllerVariableRow.tsx
/**
 * One variable of a controller in the operator console: role, status with reasons, value,
 * engineering and operator limits, the on/off toggle and the operator range editor.
 * The draft inputs live here; the parent remounts the row (key) when the server values change.
 */

import { useState } from "react";
import type { Bounds, ControllerVariable, VariableOverride } from "../controllersApi";
import type { Translate } from "../findings";
import { numberText, reasonText, statusLevel } from "./controllersFormat";
import { StatusChip } from "./StatusChip";

export interface ControllerVariableRowProps {
  variable: ControllerVariable;
  canOperate: boolean;
  onSave: (variableId: string, override: VariableOverride) => void;
  t: Translate;
}

/** "lo .. hi" of a range, or the placeholder. */
function rangeText(range: Bounds | undefined | null, none: string): string {
  return range ? `${range.lo} .. ${range.hi}` : none;
}

/** The override that keeps the operator range the controller currently runs with. */
function currentOverride(variable: ControllerVariable, enabled: boolean): VariableOverride {
  const { operator, operator_catalogue: catalogue } = variable.limits;
  const changed = operator !== undefined && JSON.stringify(operator) !== JSON.stringify(catalogue);
  return changed ? { enabled, operator } : { enabled };
}

interface RangeEditorProps {
  variable: ControllerVariable;
  onSave: ControllerVariableRowProps["onSave"];
  t: Translate;
}

function RangeEditor({ variable, onSave, t }: RangeEditorProps) {
  const seed = variable.limits.operator ?? variable.limits.eng;
  const [lo, setLo] = useState(seed ? String(seed.lo) : "");
  const [hi, setHi] = useState(seed ? String(seed.hi) : "");
  const id = variable.id;
  const save = () => onSave(id, { enabled: variable.enabled, operator: { lo: Number(lo), hi: Number(hi) } });
  return (
    <span className="toolbar">
      <input className="field-input" type="number" aria-label={t("controllers.operatorLo", { id })} data-testid={`controller-lo-${id}`} value={lo} onChange={(event) => setLo(event.target.value)} />
      <input className="field-input" type="number" aria-label={t("controllers.operatorHi", { id })} data-testid={`controller-hi-${id}`} value={hi} onChange={(event) => setHi(event.target.value)} />
      <button type="button" className="filter-chip" data-testid={`controller-save-${id}`} onClick={save}>
        {t("controllers.save")}
      </button>
    </span>
  );
}

export function ControllerVariableRow({ variable, canOperate, onSave, t }: ControllerVariableRowProps) {
  const none = t("controllers.none");
  const id = variable.id;
  const editable = canOperate && variable.limits.eng !== undefined;
  return (
    <tr data-testid={`controller-var-${id}`}>
      <th scope="row">{id}</th>
      <td>{variable.role}</td>
      <td>
        <StatusChip level={statusLevel(variable.status)} label={variable.status ? t(`controllers.status.${variable.status}`) : none} />
        {variable.reasons.map((reason) => (
          <div key={reason} className="hint">{reasonText(t, reason)}</div>
        ))}
      </td>
      <td>
        {numberText(variable.value, none)}
        {variable.sp_value !== null && <div className="hint">{t("controllers.sp")} {numberText(variable.sp_value, none)}</div>}
      </td>
      <td>{rangeText(variable.limits.eng, none)}</td>
      <td>{editable ? <RangeEditor variable={variable} onSave={onSave} t={t} /> : rangeText(variable.limits.operator, none)}</td>
      <td>
        <label className="toolbar">
          <input
            type="checkbox"
            data-testid={`controller-enabled-${id}`}
            checked={variable.enabled}
            disabled={!canOperate}
            onChange={(event) => onSave(id, currentOverride(variable, event.target.checked))}
          />
          {t("controllers.enabled", { id })}
        </label>
      </td>
    </tr>
  );
}
