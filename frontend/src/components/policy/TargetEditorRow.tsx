// frontend/src/components/policy/TargetEditorRow.tsx
/**
 * Interactive editor row for configuring write policy limits on a single DCS target tag.
 * Every control is labelled with the tag; errors are linked to their controls with
 * aria-describedby (the panel's validation summary is the only alert).
 */

import type { ChangeEvent } from "react";
import type { Translate } from "../../findings";
import {
  STANDARD_LOOP_MODES,
  hasUnicodeLookalikes,
  parseNumberInput,
  type TargetPolicy,
} from "../../policyModel";

export interface TargetEditorRowProps {
  tag: string;
  policy: TargetPolicy;
  errors: Record<string, string>;
  onChange: (tag: string, updated: TargetPolicy) => void;
  onRemove: (tag: string) => void;
  t: Translate;
}

interface NumberInputProps {
  id: string;
  value: number;
  /** Id of the element that shows this field's error (set only while there is an error). */
  describedBy?: string;
  onChange: (val: number) => void;
  ariaLabel: string;
}

function FieldErrorText({ id, error }: { id: string; error?: string }) {
  if (!error) return null;
  return (
    <span id={id} style={{ color: "var(--status-problem)", fontSize: "0.75rem", display: "block" }}>
      {error}
    </span>
  );
}

export function NumberInput({ id, value, describedBy, onChange, ariaLabel }: NumberInputProps) {
  const handleChange = (e: ChangeEvent<HTMLInputElement>) => onChange(parseNumberInput(e.target.value));
  return (
    <input id={id} type="number" step="any" value={Number.isNaN(value) ? "" : value} onChange={handleChange}
      aria-label={ariaLabel} aria-describedby={describedBy} aria-invalid={describedBy !== undefined}
      style={{ width: "100%", minWidth: 64, boxSizing: "border-box" }} />
  );
}

interface NumberCellProps {
  id: string;
  label: string;
  value: number;
  error?: string;
  onChange: (v: number) => void;
}

/** A number cell: input plus its error text, linked by id. */
function NumberCell({ id, label, value, error, onChange }: NumberCellProps) {
  const errId = `${id}-err`;
  return (
    <td>
      <NumberInput id={id} value={value} describedBy={error ? errId : undefined} onChange={onChange} ariaLabel={label} />
      <FieldErrorText id={errId} error={error} />
    </td>
  );
}

interface LimitsCellProps {
  tag: string;
  limits: [number, number];
  error?: string;
  onChange: (lim: [number, number]) => void;
  t: Translate;
}

function LimitsCell({ tag, limits, error, onChange, t }: LimitsCellProps) {
  const errId = `limits-${tag}-err`;
  const describedBy = error ? errId : undefined;
  return (
    <td style={{ minWidth: 140 }}>
      <div style={{ display: "flex", gap: 4 }}>
        <NumberInput id={`limit-low-${tag}`} value={limits[0]} describedBy={describedBy} onChange={(v) => onChange([v, limits[1]])}
          ariaLabel={`${t("policy.draft.limitsLow")} ${tag}`} />
        <NumberInput id={`limit-high-${tag}`} value={limits[1]} describedBy={describedBy} onChange={(v) => onChange([limits[0], v])}
          ariaLabel={`${t("policy.draft.limitsHigh")} ${tag}`} />
      </div>
      <FieldErrorText id={errId} error={error} />
    </td>
  );
}

interface ModeCheckboxProps {
  mode: string;
  checked: boolean;
  describedBy?: string;
  onToggle: () => void;
}

function ModeCheckbox({ mode, checked, describedBy, onToggle }: ModeCheckboxProps) {
  return (
    <label style={{ display: "inline-flex", alignItems: "center", gap: 2, fontSize: "0.8rem" }}>
      <input type="checkbox" checked={checked} onChange={onToggle} aria-describedby={describedBy} />
      {mode}
    </label>
  );
}

interface LoopModesCellProps {
  tag: string;
  modes: string[];
  error?: string;
  onChange: (m: string[]) => void;
  t: Translate;
}

function LoopModesCell({ tag, modes, error, onChange, t }: LoopModesCellProps) {
  const errId = `modes-${tag}-err`;
  const describedBy = error ? errId : undefined;
  const toggle = (m: string) => onChange(modes.includes(m) ? modes.filter((item) => item !== m) : [...modes, m]);
  return (
    <td style={{ minWidth: 160 }}>
      <div role="group" aria-label={`${t("policy.draft.allowedModes")} ${tag}`} aria-describedby={describedBy}
        style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
        {STANDARD_LOOP_MODES.map((mode) => (
          <ModeCheckbox key={mode} mode={mode} checked={modes.includes(mode)} describedBy={describedBy} onToggle={() => toggle(mode)} />
        ))}
      </div>
      <FieldErrorText id={errId} error={error} />
    </td>
  );
}

function TagCell({ tag, t }: { tag: string; t: Translate }) {
  return (
    <td style={{ minWidth: 110 }}>
      <strong>{tag}</strong>
      {hasUnicodeLookalikes(tag) && (
        <span style={{ color: "var(--status-warning)", fontSize: "0.75rem", display: "block" }}>
          {t("policy.validation.tagLookalikeWarning")}
        </span>
      )}
    </td>
  );
}

function RemoveButtonCell({ tag, onRemove, t }: { tag: string; onRemove: (tag: string) => void; t: Translate }) {
  return (
    <td>
      <button type="button" onClick={() => onRemove(tag)} data-testid={`remove-target-${tag}`}
        aria-label={`${t("policy.draft.removeTarget")} ${tag}`} style={{ color: "var(--status-problem)" }}>
        {t("policy.draft.removeTarget")}
      </button>
    </td>
  );
}

const FIRST_FIELDS = [
  { key: "max_step", idPrefix: "step", label: "policy.draft.maxStep" },
  { key: "max_rate_per_s", idPrefix: "rate", label: "policy.draft.maxRate" },
  { key: "min_interval_s", idPrefix: "interval", label: "policy.draft.minInterval" },
] as const;

const LAST_FIELDS = [
  { key: "hold_off_s", idPrefix: "holdoff", label: "policy.draft.holdOff" },
  { key: "watchdog_s", idPrefix: "watchdog", label: "policy.draft.watchdog" },
  { key: "readback_tolerance", idPrefix: "tol", label: "policy.draft.readbackTol" },
] as const;

type ScalarField = (typeof FIRST_FIELDS)[number] | (typeof LAST_FIELDS)[number];

/** Translates an error key when there is one. */
function errorText(errors: Record<string, string>, key: string, t: Translate): string | undefined {
  return errors[key] ? t(errors[key]) : undefined;
}

export function TargetEditorRow({ tag, policy, errors, onChange, onRemove, t }: TargetEditorRowProps) {
  const update = (patch: Partial<TargetPolicy>) => onChange(tag, { ...policy, ...patch });
  const cell = (f: ScalarField) => (
    <NumberCell key={f.key} id={`${f.idPrefix}-${tag}`} label={`${t(f.label)} ${tag}`} value={policy[f.key]}
      error={errorText(errors, f.key, t)} onChange={(v) => update({ [f.key]: v })} />
  );
  return (
    <tr data-testid={`target-editor-row-${tag}`}>
      <TagCell tag={tag} t={t} />
      <LimitsCell tag={tag} limits={policy.limits} error={errorText(errors, "limits", t)} onChange={(lim) => update({ limits: lim })} t={t} />
      {FIRST_FIELDS.map(cell)}
      <LoopModesCell tag={tag} modes={policy.allowed_loop_modes} error={errorText(errors, "allowed_loop_modes", t)}
        onChange={(m) => update({ allowed_loop_modes: m })} t={t} />
      {LAST_FIELDS.map(cell)}
      <RemoveButtonCell tag={tag} onRemove={onRemove} t={t} />
    </tr>
  );
}
