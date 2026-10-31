// src/components/CatalogueWizard.tsx
// Catalogue mapping wizard (Phase 1, #37).
// Guides the user through selecting tag sources, inferring and adjusting canonical roles,
// reviewing assembled control loops, and persisting the mapping into the site catalogue.

import { useEffect, useState } from "react";
import {
  fetchDatasets,
  fetchTags,
  saveCatalogueMapping,
  suggestCatalogueRoles,
  type CatalogueLoop,
  type CatalogueSignal,
  type DatasetSummary,
} from "../api";
import type { Translate } from "../findings";
import { Stepper, type StepInfo, type StepState } from "./Stepper";

export type WizardPhase = "source" | "tags" | "roles" | "loops" | "confirm";

const PHASES: readonly WizardPhase[] = ["source", "tags", "roles", "loops", "confirm"];
const ALL_ROLES = ["pv", "sp", "out", "mode", "fb", "input", "target", "lab", "dv"] as const;
const LOOP_ROLES = new Set(["pv", "sp", "out", "mode", "fb", "dv"]);

export interface CatalogueWizardProps {
  t: Translate;
  onSaved?: () => void;
  onClose?: () => void;
}

export function CatalogueWizard({ t, onSaved, onClose }: CatalogueWizardProps) {
  const [phase, setPhase] = useState<WizardPhase>("source");
  const [datasets, setDatasets] = useState<DatasetSummary[]>([]);
  const [sourceMode, setSourceMode] = useState<"dataset" | "manual">("dataset");
  const [selectedDs, setSelectedDs] = useState("");
  const [rawText, setRawText] = useState("");
  const [tags, setTags] = useState<string[]>([]);
  const [signals, setSignals] = useState<CatalogueSignal[]>([]);
  const [loops, setLoops] = useState<CatalogueLoop[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    fetchDatasets()
      .then((ds) => {
        setDatasets(ds);
        if (ds.length > 0) setSelectedDs(ds[0].id);
      })
      .catch(() => {});
  }, []);

  const steps = buildStepInfos(phase, t);

  const handleInspectTags = async () => {
    setBusy(true);
    setError(null);
    try {
      const extracted = await resolveTagsFromSource(sourceMode, selectedDs, rawText);
      setTags(extracted);
      setPhase("tags");
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  const handleInferRoles = async () => {
    setBusy(true);
    setError(null);
    try {
      const res = await suggestCatalogueRoles(tags);
      setSignals(res.signals);
      setLoops(res.loops);
      setPhase("roles");
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  const handleSave = async () => {
    setBusy(true);
    setError(null);
    try {
      await saveCatalogueMapping({ signals, loops });
      setSaved(true);
      if (onSaved) onSaved();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="catalogue-wizard panel" data-testid="catalogue-wizard">
      <div className="section-head">
        <h2>{t("catalogue.wizard.title")}</h2>
        <p className="section-subtitle">{t("catalogue.wizard.subtitle")}</p>
      </div>

      <Stepper
        steps={steps}
        ariaLabel={t("catalogue.wizard.stepper")}
        stateLabels={{
          todo: t("tuning.stepState.todo"),
          active: t("tuning.stepState.active"),
          done: t("tuning.stepState.done"),
          blocked: t("tuning.stepState.blocked"),
        }}
      />

      {error && <p className="status status-error" role="alert">{error}</p>}

      {phase === "source" && (
        <SourceStep
          sourceMode={sourceMode}
          selectedDs={selectedDs}
          rawText={rawText}
          datasets={datasets}
          busy={busy}
          onModeChange={setSourceMode}
          onDsChange={setSelectedDs}
          onTextChange={setRawText}
          onNext={handleInspectTags}
          t={t}
        />
      )}

      {phase === "tags" && (
        <TagsStep
          tags={tags}
          busy={busy}
          onBack={() => setPhase("source")}
          onNext={handleInferRoles}
          t={t}
        />
      )}

      {phase === "roles" && (
        <RolesStep
          signals={signals}
          onSignalsChange={setSignals}
          onBack={() => setPhase("tags")}
          onNext={() => setPhase("loops")}
          t={t}
        />
      )}

      {phase === "loops" && (
        <LoopsStep
          loops={loops}
          onLoopsChange={setLoops}
          onBack={() => setPhase("roles")}
          onNext={() => setPhase("confirm")}
          t={t}
        />
      )}

      {phase === "confirm" && (
        <ConfirmStep
          signals={signals}
          loops={loops}
          busy={busy}
          saved={saved}
          onBack={() => setPhase("loops")}
          onSave={handleSave}
          onClose={onClose}
          t={t}
        />
      )}
    </section>
  );
}

function buildStepInfos(currentPhase: WizardPhase, t: Translate): StepInfo[] {
  const currentIndex = PHASES.indexOf(currentPhase);
  return PHASES.map((p, index) => {
    let state: StepState = "todo";
    if (index === currentIndex) state = "active";
    else if (index < currentIndex) state = "done";
    return { id: p, label: t(`catalogue.wizard.step.${p}`), state };
  });
}

async function resolveTagsFromSource(
  mode: "dataset" | "manual",
  datasetId: string,
  rawText: string,
): Promise<string[]> {
  if (mode === "dataset") {
    if (!datasetId) return [];
    const rows = await fetchTags(datasetId);
    return rows.map((r) => r.id);
  }
  return rawText
    .split(/[\r\n,;]+/)
    .map((s) => s.trim())
    .filter((s) => s.length > 0);
}

interface SourceStepProps {
  sourceMode: "dataset" | "manual";
  selectedDs: string;
  rawText: string;
  datasets: DatasetSummary[];
  busy: boolean;
  onModeChange: (m: "dataset" | "manual") => void;
  onDsChange: (ds: string) => void;
  onTextChange: (val: string) => void;
  onNext: () => void;
  t: Translate;
}

function SourceStep(props: SourceStepProps) {
  const { sourceMode, selectedDs, rawText, datasets, busy, onModeChange, onDsChange, onTextChange, onNext, t } = props;
  return (
    <div className="wizard-step" data-testid="wizard-step-source">
      <div className="field-group">
        <label className="filter-chip">
          <input
            type="radio"
            name="sourceMode"
            checked={sourceMode === "dataset"}
            onChange={() => onModeChange("dataset")}
          />
          {t("catalogue.wizard.sourceDataset")}
        </label>
        <label className="filter-chip">
          <input
            type="radio"
            name="sourceMode"
            checked={sourceMode === "manual"}
            onChange={() => onModeChange("manual")}
          />
          {t("catalogue.wizard.sourceManual")}
        </label>
      </div>

      {sourceMode === "dataset" ? (
        <label className="field">
          <span className="field-label">{t("catalogue.wizard.sourceDataset")}</span>
          <select
            className="field-input"
            value={selectedDs}
            data-testid="wizard-dataset-select"
            onChange={(e) => onDsChange(e.target.value)}
          >
            {datasets.map((d) => (
              <option key={d.id} value={d.id}>{d.id}</option>
            ))}
          </select>
        </label>
      ) : (
        <label className="field">
          <span className="field-label">{t("catalogue.wizard.sourceManual")}</span>
          <textarea
            className="field-input"
            rows={5}
            value={rawText}
            data-testid="wizard-manual-textarea"
            placeholder={t("catalogue.wizard.pastePlaceholder")}
            onChange={(e) => onTextChange(e.target.value)}
          />
        </label>
      )}

      <div className="action-row">
        <button
          type="button"
          className="button button-primary"
          disabled={busy || (sourceMode === "manual" && !rawText.trim())}
          onClick={onNext}
        >
          {t("catalogue.wizard.nextTags")}
        </button>
      </div>
    </div>
  );
}

interface TagsStepProps {
  tags: string[];
  busy: boolean;
  onBack: () => void;
  onNext: () => void;
  t: Translate;
}

function TagsStep({ tags, busy, onBack, onNext, t }: TagsStepProps) {
  return (
    <div className="wizard-step" data-testid="wizard-step-tags">
      <p className="notice">{tags.length} tags discovered.</p>
      <div className="tag-list" style={{ maxHeight: "250px", overflowY: "auto" }}>
        {tags.map((tag) => (
          <span key={tag} className="tag-badge" style={{ display: "inline-block", margin: "2px", padding: "4px 8px" }}>
            {tag}
          </span>
        ))}
      </div>
      <div className="action-row" style={{ marginTop: "1rem" }}>
        <button type="button" className="button" onClick={onBack}>{t("catalogue.wizard.back")}</button>
        <button type="button" className="button button-primary" disabled={busy || tags.length === 0} onClick={onNext}>
          {busy ? t("catalogue.wizard.inferring") : t("catalogue.wizard.nextRoles")}
        </button>
      </div>
    </div>
  );
}

interface RolesStepProps {
  signals: CatalogueSignal[];
  onSignalsChange: (sigs: CatalogueSignal[]) => void;
  onBack: () => void;
  onNext: () => void;
  t: Translate;
}

function RolesStep({ signals, onSignalsChange, onBack, onNext, t }: RolesStepProps) {
  const updateSignal = (index: number, patch: Partial<CatalogueSignal>) => {
    const next = [...signals];
    next[index] = { ...next[index], ...patch };
    onSignalsChange(next);
  };

  return (
    <div className="wizard-step" data-testid="wizard-step-roles">
      <table className="data-table">
        <thead>
          <tr>
            <th>Tag</th>
            <th>Role</th>
            <th>Loop ID</th>
            <th>Module</th>
          </tr>
        </thead>
        <tbody>
          {signals.map((sig, idx) => (
            <tr key={sig.tag}>
              <td><strong>{sig.tag}</strong></td>
              <td>
                <select
                  value={sig.role}
                  aria-label={`Role for ${sig.tag}`}
                  onChange={(e) => updateSignal(idx, { role: e.target.value as CatalogueSignal["role"] })}
                >
                  {ALL_ROLES.map((r) => (
                    <option key={r} value={r}>{r}</option>
                  ))}
                </select>
              </td>
              <td>
                <input
                  type="text"
                  value={sig.loop ?? ""}
                  placeholder={LOOP_ROLES.has(sig.role) ? "Loop ID" : "-"}
                  disabled={!LOOP_ROLES.has(sig.role)}
                  aria-label={`Loop ID for ${sig.tag}`}
                  onChange={(e) => updateSignal(idx, { loop: e.target.value || undefined })}
                />
              </td>
              <td>
                <select
                  value={sig.module ?? ""}
                  aria-label={`Module for ${sig.tag}`}
                  onChange={(e) => updateSignal(idx, { module: (e.target.value as CatalogueSignal["module"]) || undefined })}
                >
                  <option value="">(all modules)</option>
                  <option value="loops">loops</option>
                  <option value="anomaly">anomaly</option>
                  <option value="softsensor">softsensor</option>
                </select>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="action-row" style={{ marginTop: "1rem" }}>
        <button type="button" className="button" onClick={onBack}>{t("catalogue.wizard.back")}</button>
        <button type="button" className="button button-primary" onClick={onNext}>
          {t("catalogue.wizard.nextLoops")}
        </button>
      </div>
    </div>
  );
}

interface LoopsStepProps {
  loops: CatalogueLoop[];
  onLoopsChange: (loops: CatalogueLoop[]) => void;
  onBack: () => void;
  onNext: () => void;
  t: Translate;
}

function LoopsStep({ loops, onLoopsChange, onBack, onNext, t }: LoopsStepProps) {
  const updateLoop = (index: number, patch: Partial<CatalogueLoop>) => {
    const next = [...loops];
    next[index] = { ...next[index], ...patch };
    onLoopsChange(next);
  };

  return (
    <div className="wizard-step" data-testid="wizard-step-loops">
      {loops.length === 0 ? (
        <p className="notice banner-warning">{t("catalogue.wizard.noLoops")}</p>
      ) : (
        <table className="data-table">
          <thead>
            <tr>
              <th>ID</th>
              <th>PV</th>
              <th>SP</th>
              <th>OUT</th>
              <th>Mode</th>
              <th>Action</th>
            </tr>
          </thead>
          <tbody>
            {loops.map((loop, idx) => (
              <tr key={loop.id}>
                <td><strong>{loop.id}</strong></td>
                <td>{loop.pv}</td>
                <td>{loop.sp ?? "-"}</td>
                <td>{loop.out}</td>
                <td>{loop.mode ?? "-"}</td>
                <td>
                  <select
                    value={loop.action ?? "direct"}
                    aria-label={`Action for loop ${loop.id}`}
                    onChange={(e) => updateLoop(idx, { action: e.target.value as "direct" | "reverse" })}
                  >
                    <option value="direct">direct</option>
                    <option value="reverse">reverse</option>
                  </select>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <div className="action-row" style={{ marginTop: "1rem" }}>
        <button type="button" className="button" onClick={onBack}>{t("catalogue.wizard.back")}</button>
        <button type="button" className="button button-primary" onClick={onNext}>
          {t("catalogue.wizard.nextConfirm")}
        </button>
      </div>
    </div>
  );
}

interface ConfirmStepProps {
  signals: CatalogueSignal[];
  loops: CatalogueLoop[];
  busy: boolean;
  saved: boolean;
  onBack: () => void;
  onSave: () => void;
  onClose?: () => void;
  t: Translate;
}

function ConfirmStep(props: ConfirmStepProps) {
  const { signals, loops, busy, saved, onBack, onSave, onClose, t } = props;
  return (
    <div className="wizard-step" data-testid="wizard-step-confirm">
      {saved ? (
        <div className="notice banner-success" data-testid="wizard-success-notice">
          <p>{t("catalogue.wizard.saved")}</p>
          {onClose && (
            <button type="button" className="button button-primary" onClick={onClose}>
              {t("catalogue.wizard.done")}
            </button>
          )}
        </div>
      ) : (
        <>
          <p className="notice">
            Ready to persist {signals.length} signals and {loops.length} loops into the site catalogue.
          </p>
          <div className="action-row">
            <button type="button" className="button" onClick={onBack}>{t("catalogue.wizard.back")}</button>
            <button
              type="button"
              className="button button-primary"
              disabled={busy}
              data-testid="wizard-save-btn"
              onClick={onSave}
            >
              {busy ? t("catalogue.wizard.saving") : t("catalogue.wizard.save")}
            </button>
          </div>
        </>
      )}
    </div>
  );
}
