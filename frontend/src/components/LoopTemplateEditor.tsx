// src/components/LoopTemplateEditor.tsx
//
// Editor of the loop templates (PRODUCT 4.1): the engineer picks a loop type, changes its
// expected dynamics, KPI limits, diagnosis rules, tuning target, allowed tests and default
// step, and saves a site copy. The packaged template stays unchanged as the fallback.

import { useEffect, useState, type ReactElement } from "react";
import type { Translate } from "../findings";
import {
  DIAGNOSIS_RULES,
  PROCESS_KINDS,
  TEST_TYPES,
  TUNING_RULES,
  invalidRangeFields,
  listLoopTemplates,
  saveLoopTemplate,
  toggleValue,
  type DiagnosisRule,
  type LoopDynamics,
  type LoopKpiThresholds,
  type LoopTemplate,
  type LoopTuning,
  type LoopTests,
  type ProcessKind,
  type TestType,
  type TuningRule,
} from "../loopTemplate";

/** Whether the template library is being fetched, has arrived, or failed. */
type LoadStatus = "loading" | "ready" | "error";

/** A short message shown under the form after a load or save attempt. */
interface Notice {
  kind: "ok" | "error";
  text: string;
}

/** One labelled numeric input; the parent owns the value and the invalid flag. */
function NumberField({
  id,
  label,
  value,
  isInvalid,
  onChange,
}: {
  id: string;
  label: string;
  value: number;
  isInvalid: boolean;
  onChange: (value: number) => void;
}) {
  return (
    <label className="field" htmlFor={id}>
      <span className="field-label">{label}</span>
      <input
        id={id}
        className="field-input"
        type="number"
        step="any"
        value={Number.isFinite(value) ? value : ""}
        aria-invalid={isInvalid}
        onChange={(event) => onChange(event.target.value === "" ? Number.NaN : Number(event.target.value))}
      />
    </label>
  );
}

/** One labelled checkbox used for the diagnosis rules and the allowed tests. */
function CheckField({
  id,
  label,
  checked,
  onChange,
}: {
  id: string;
  label: string;
  checked: boolean;
  onChange: () => void;
}) {
  return (
    <label className="field field-inline" htmlFor={id}>
      <input id={id} type="checkbox" checked={checked} onChange={onChange} />
      <span>{label}</span>
    </label>
  );
}

/** Props shared by every section of the form. */
interface SectionProps {
  template: LoopTemplate;
  invalid: ReadonlySet<string>;
  onTemplate: (next: LoopTemplate) => void;
  t: Translate;
}

/** Identity fields: key (read-only), label, description and process kind. */
function IdentityFields({ template, onTemplate, t }: SectionProps): ReactElement {
  return (
    <fieldset className="loop-template-section">
      <legend>{t("loopTemplates.identity")}</legend>
      <p className="field">
        <span className="field-label">{t("loopTemplates.key")}</span>
        <code data-testid="loop-template-key">{template.key}</code>
      </p>
      <label className="field" htmlFor="loop-template-label">
        <span className="field-label">{t("loopTemplates.label")}</span>
        <input
          id="loop-template-label"
          className="field-input"
          type="text"
          value={template.label}
          onChange={(event) => onTemplate({ ...template, label: event.target.value })}
        />
      </label>
      <label className="field" htmlFor="loop-template-description">
        <span className="field-label">{t("loopTemplates.description")}</span>
        <textarea
          id="loop-template-description"
          className="field-input"
          value={template.description ?? ""}
          onChange={(event) => onTemplate({ ...template, description: event.target.value })}
        />
      </label>
      <label className="field" htmlFor="loop-template-process-kind">
        <span className="field-label">{t("loopTemplates.processKind")}</span>
        <select
          id="loop-template-process-kind"
          className="field-input"
          value={template.process_kind}
          onChange={(event) =>
            onTemplate({ ...template, process_kind: event.target.value as ProcessKind })
          }
        >
          {PROCESS_KINDS.map((kind) => (
            <option key={kind} value={kind}>
              {t(`loopTemplates.processKind.${kind}`)}
            </option>
          ))}
        </select>
      </label>
    </fieldset>
  );
}

/** Expected dynamics range: gain, dominant time constant and dead time, each min and max. */
function DynamicsFields({ template, invalid, onTemplate, t }: SectionProps): ReactElement {
  const setField = (field: keyof LoopDynamics, value: number) =>
    onTemplate({ ...template, dynamics: { ...template.dynamics, [field]: value } });
  const bound = (field: keyof LoopDynamics, name: string, invalidKey: string, side: "min" | "max") => (
    <NumberField
      id={`loop-template-${field}`}
      label={`${name} (${t(`loopTemplates.dynamics.${side}`)})`}
      value={template.dynamics[field]}
      isInvalid={invalid.has(invalidKey)}
      onChange={(value) => setField(field, value)}
    />
  );
  return (
    <fieldset className="loop-template-section">
      <legend>{t("loopTemplates.dynamics")}</legend>
      {bound("gain_min", t("loopTemplates.dynamics.gain"), "dynamics.gain", "min")}
      {bound("gain_max", t("loopTemplates.dynamics.gain"), "dynamics.gain", "max")}
      {bound("time_constant_s_min", t("loopTemplates.dynamics.timeConstant"), "dynamics.timeConstant", "min")}
      {bound("time_constant_s_max", t("loopTemplates.dynamics.timeConstant"), "dynamics.timeConstant", "max")}
      {bound("dead_time_s_min", t("loopTemplates.dynamics.deadTime"), "dynamics.deadTime", "min")}
      {bound("dead_time_s_max", t("loopTemplates.dynamics.deadTime"), "dynamics.deadTime", "max")}
    </fieldset>
  );
}

/** KPI limits; every share is a fraction between 0 and 1. */
function KpiFields({ template, invalid, onTemplate, t }: SectionProps): ReactElement {
  const setField = (field: keyof LoopKpiThresholds, value: number) =>
    onTemplate({ ...template, kpi_thresholds: { ...template.kpi_thresholds, [field]: value } });
  const fields: Array<[keyof LoopKpiThresholds, string, string]> = [
    ["service_factor_min", "kpi.serviceFactor", "service_factor_min"],
    ["saturation_share_max", "kpi.saturation", "saturation_share_max"],
    ["oscillation_index_max", "kpi.oscillation", "oscillation_index_max"],
    ["noise_ratio_max", "kpi.noise", "noise_ratio_max"],
  ];
  return (
    <fieldset className="loop-template-section">
      <legend>{t("loopTemplates.kpi")}</legend>
      {fields.map(([field, labelKey, invalidKey]) => (
        <NumberField
          key={field}
          id={`loop-template-${field}`}
          label={t(`loopTemplates.${labelKey}`)}
          value={template.kpi_thresholds[field]}
          isInvalid={invalid.has(invalidKey)}
          onChange={(value) => setField(field, value)}
        />
      ))}
    </fieldset>
  );
}

/** Diagnosis rules that apply to this loop type, in the fixed product order. */
function DiagnosisFields({ template, onTemplate, t }: SectionProps): ReactElement {
  return (
    <fieldset className="loop-template-section">
      <legend>{t("loopTemplates.diagnosis")}</legend>
      {DIAGNOSIS_RULES.map((rule) => (
        <CheckField
          key={rule}
          id={`loop-template-diagnosis-${rule}`}
          label={t(`loopTemplates.diagnosis.${rule}`)}
          checked={template.diagnosis_rules.includes(rule)}
          onChange={() =>
            onTemplate({
              ...template,
              diagnosis_rules: toggleValue<DiagnosisRule>(template.diagnosis_rules, rule),
            })
          }
        />
      ))}
    </fieldset>
  );
}

/** Preferred tuning rule, closed-loop target and default robustness slider position. */
function TuningFields({ template, invalid, onTemplate, t }: SectionProps): ReactElement {
  const setTuning = (change: Partial<LoopTuning>) =>
    onTemplate({ ...template, tuning: { ...template.tuning, ...change } });
  return (
    <fieldset className="loop-template-section">
      <legend>{t("loopTemplates.tuning")}</legend>
      <label className="field" htmlFor="loop-template-tuning-rule">
        <span className="field-label">{t("loopTemplates.tuning.rule")}</span>
        <select
          id="loop-template-tuning-rule"
          className="field-input"
          value={template.tuning.rule}
          onChange={(event) => setTuning({ rule: event.target.value as TuningRule })}
        >
          {TUNING_RULES.map((rule) => (
            <option key={rule} value={rule}>
              {t(`loopTemplates.tuning.rule.${rule}`)}
            </option>
          ))}
        </select>
      </label>
      <NumberField
        id="loop-template-tuning-target"
        label={t("loopTemplates.tuning.target")}
        value={template.tuning.target_closed_loop_time_constant_ratio}
        isInvalid={invalid.has("tuning.target")}
        onChange={(value) => setTuning({ target_closed_loop_time_constant_ratio: value })}
      />
    </fieldset>
  );
}

/** Allowed test types and the safe default OUT step. */
function TestFields({ template, invalid, onTemplate, t }: SectionProps): ReactElement {
  const setTests = (change: Partial<LoopTests>) =>
    onTemplate({ ...template, tests: { ...template.tests, ...change } });
  return (
    <fieldset className="loop-template-section">
      <legend>{t("loopTemplates.tests")}</legend>
      {TEST_TYPES.map((test) => (
        <CheckField
          key={test}
          id={`loop-template-test-${test}`}
          label={t(`loopTemplates.tests.${test}`)}
          checked={template.tests.allowed.includes(test)}
          onChange={() =>
            setTests({ allowed: toggleValue<TestType>(template.tests.allowed, test) })
          }
        />
      ))}
      <NumberField
        id="loop-template-default-step"
        label={t("loopTemplates.tests.defaultStep")}
        value={template.tests.default_step_pct}
        isInvalid={invalid.has("tests.defaultStep")}
        onChange={(value) => setTests({ default_step_pct: value })}
      />
    </fieldset>
  );
}

/** The form of one selected template, with its save button and status message. */
function TemplateForm({
  draft,
  notice,
  saving,
  onDraft,
  onSave,
  t,
}: {
  draft: LoopTemplate;
  notice: Notice | null;
  saving: boolean;
  onDraft: (next: LoopTemplate) => void;
  onSave: () => void;
  t: Translate;
}): ReactElement {
  const invalid = new Set(invalidRangeFields(draft));
  const section = { template: draft, invalid, onTemplate: onDraft, t };
  return (
    <form
      className="loop-template-form"
      onSubmit={(event) => {
        event.preventDefault();
        onSave();
      }}
    >
      <IdentityFields {...section} />
      <DynamicsFields {...section} />
      <KpiFields {...section} />
      <DiagnosisFields {...section} />
      <TuningFields {...section} />
      <TestFields {...section} />
      {invalid.size > 0 && (
        <p className="status status-error" role="alert">
          {t("loopTemplates.rangeError")}
        </p>
      )}
      <p className="form-actions">
        <button
          type="submit"
          className="filter-chip"
          data-testid="loop-template-save"
          disabled={saving || invalid.size > 0}
        >
          {saving ? t("loopTemplates.saving") : t("loopTemplates.save")}
        </button>
      </p>
      {notice !== null && (
        <p className={notice.kind === "ok" ? "status" : "status status-error"} role="status">
          {notice.text}
        </p>
      )}
    </form>
  );
}

/** Load the library once and keep the selected template as the editable draft. */
function useTemplateLibrary() {
  const [templates, setTemplates] = useState<LoopTemplate[]>([]);
  const [draft, setDraft] = useState<LoopTemplate | null>(null);
  const [status, setStatus] = useState<LoadStatus>("loading");
  const [failure, setFailure] = useState("");

  useEffect(() => {
    let isCancelled = false;
    listLoopTemplates()
      .then((loaded) => {
        if (isCancelled) return;
        setTemplates(loaded);
        setDraft(loaded[0] ?? null);
        setStatus("ready");
      })
      .catch((error: unknown) => {
        if (isCancelled) return;
        setFailure(error instanceof Error ? error.message : String(error));
        setStatus("error");
      });
    return () => {
      isCancelled = true;
    };
  }, []);

  const select = (key: string) => setDraft(templates.find((one) => one.key === key) ?? null);
  return { templates, draft, status, failure, select, setDraft, setTemplates };
}

/**
 * Editor of the loop template library: choose a type, edit its fields, save a site copy.
 *
 * A save sends the whole template; the server validates it against the same JSON Schema the
 * packaged loader uses, so the browser cannot store a template the engine would reject.
 */
export function LoopTemplateEditor({ t }: { t: Translate }): ReactElement {
  const library = useTemplateLibrary();
  const [notice, setNotice] = useState<Notice | null>(null);
  const [saving, setSaving] = useState(false);

  const save = async () => {
    const draft = library.draft;
    if (draft === null) return;
    setSaving(true);
    setNotice(null);
    try {
      const saved = await saveLoopTemplate(draft.key, draft);
      library.setTemplates((list) => list.map((one) => (one.key === saved.key ? saved : one)));
      library.setDraft(saved);
      setNotice({ kind: "ok", text: t("loopTemplates.saved") });
    } catch (error) {
      const reason = error instanceof Error ? error.message : String(error);
      setNotice({ kind: "error", text: `${t("loopTemplates.saveError")}: ${reason}` });
    } finally {
      setSaving(false);
    }
  };

  return (
    <section className="loop-template-editor" aria-label={t("loopTemplates.title")} data-testid="loop-template-editor">
      <h2>{t("loopTemplates.title")}</h2>
      <p>{t("loopTemplates.intro")}</p>
      {library.status === "loading" && (
        <p className="status" role="status">
          {t("loopTemplates.loading")}
        </p>
      )}
      {library.status === "error" && (
        <p className="status status-error" role="alert">
          {t("loopTemplates.loadError")}: {library.failure}
        </p>
      )}
      {library.status === "ready" && library.draft !== null && (
        <>
          <label className="field" htmlFor="loop-template-select">
            <span className="field-label">{t("loopTemplates.select")}</span>
            <select
              id="loop-template-select"
              className="field-input"
              data-testid="loop-template-select"
              value={library.draft.key}
              onChange={(event) => {
                setNotice(null);
                library.select(event.target.value);
              }}
            >
              {library.templates.map((one) => (
                <option key={one.key} value={one.key}>
                  {one.label} ({one.key})
                </option>
              ))}
            </select>
          </label>
          <p className="field-help">
            {t("loopTemplates.origin")}: {t(`loopTemplates.origin.${library.draft.origin ?? "builtin"}`)}
          </p>
          <TemplateForm
            draft={library.draft}
            notice={notice}
            saving={saving}
            onDraft={library.setDraft}
            onSave={() => void save()}
            t={t}
          />
        </>
      )}
    </section>
  );
}
