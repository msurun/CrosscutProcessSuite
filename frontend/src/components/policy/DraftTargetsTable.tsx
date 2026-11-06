// frontend/src/components/policy/DraftTargetsTable.tsx
/**
 * Table container for editing protected target configurations in the policy draft.
 * Handles adding new target tags, zero-targets boundary warnings, and responsive layout.
 */

import { useState } from "react";
import type { Translate } from "../../findings";
import {
  hasUnicodeLookalikes,
  validateTag,
  validateTarget,
  type TargetPolicy,
} from "../../policyModel";
import { TargetEditorRow } from "./TargetEditorRow";

export interface DraftTargetsTableProps {
  targets: Record<string, TargetPolicy>;
  onChange: (targets: Record<string, TargetPolicy>) => void;
  t: Translate;
}

const DEFAULT_TARGET_TEMPLATE: TargetPolicy = {
  limits: [0, 100],
  max_step: 1.0,
  max_rate_per_s: 0.5,
  min_interval_s: 1.0,
  allowed_loop_modes: ["CAS", "AUTO"],
  hold_off_s: 5.0,
  watchdog_s: 10.0,
  readback_tolerance: 0.1,
};

function TagNoticeMessages({ tagError, lookalike, t }: { tagError: string | null; lookalike: boolean; t: Translate }) {
  return (
    <>
      {tagError && (
        <span id="add-target-err" style={{ color: "var(--status-problem)", fontSize: "0.85rem" }}>
          {t(tagError)}
        </span>
      )}
      {lookalike && (
        <span id="add-target-warn" style={{ color: "var(--status-warning)", fontSize: "0.85rem" }}>
          {t("policy.validation.tagLookalikeWarning")}
        </span>
      )}
    </>
  );
}

function AddTargetInputs({ value, describedBy, onChange, onAdd, t }: { value: string; describedBy?: string; onChange: (v: string) => void; onAdd: () => void; t: Translate }) {
  return (
    <div className="toolbar" style={{ flexWrap: "wrap", gap: 8 }}>
      <input
        type="text"
        value={value}
        placeholder={t("policy.draft.newTag")}
        onChange={(e) => onChange(e.target.value)}
        aria-label={t("policy.draft.newTag")}
        aria-describedby={describedBy}
        data-testid="add-target-input"
      />
      <button type="button" onClick={onAdd} data-testid="add-target-button">
        {t("policy.draft.addTarget")}
      </button>
    </div>
  );
}

/** ids of the notices that currently describe the new-tag input. */
function describedByIds(tagError: string | null, newTag: string): string | undefined {
  const ids = [tagError ? "add-target-err" : "", hasUnicodeLookalikes(newTag) ? "add-target-warn" : ""].filter(Boolean);
  return ids.length > 0 ? ids.join(" ") : undefined;
}

function AddTargetBar({ existingTags, onAdd, t }: { existingTags: string[]; onAdd: (tag: string) => void; t: Translate }) {
  const [newTag, setNewTag] = useState("");
  const [tagError, setTagError] = useState<string | null>(null);

  const handleAdd = () => {
    const err = validateTag(newTag, existingTags);
    if (err) setTagError(err);
    else { onAdd(newTag.trim()); setNewTag(""); setTagError(null); }
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 4, marginBottom: 12 }}>
      <AddTargetInputs value={newTag} describedBy={describedByIds(tagError, newTag)} onChange={(v) => { setNewTag(v); setTagError(null); }} onAdd={handleAdd} t={t} />
      <TagNoticeMessages tagError={tagError} lookalike={hasUnicodeLookalikes(newTag)} t={t} />
    </div>
  );
}

function TableHeader({ t }: { t: Translate }) {
  return (
    <thead>
      <tr>
        <th>{t("policy.draft.tag")}</th>
        <th>{t("policy.draft.limits")}</th>
        <th>{t("policy.draft.maxStep")}</th>
        <th>{t("policy.draft.maxRate")}</th>
        <th>{t("policy.draft.minInterval")}</th>
        <th>{t("policy.draft.allowedModes")}</th>
        <th>{t("policy.draft.holdOff")}</th>
        <th>{t("policy.draft.watchdog")}</th>
        <th>{t("policy.draft.readbackTol")}</th>
        <th>{t("policy.draft.removeTarget")}</th>
      </tr>
    </thead>
  );
}

function ZeroTargetsAlert({ count, t }: { count: number; t: Translate }) {
  if (count > 0) return null;
  return (
    <div className="notice notice-warning" role="status" data-testid="zero-targets-warning">
      <p>{t("policy.draft.zeroTargetsWarning")}</p>
    </div>
  );
}

interface TargetsTableProps {
  tags: string[];
  targets: Record<string, TargetPolicy>;
  onChange: (tag: string, updated: TargetPolicy) => void;
  onRemove: (tag: string) => void;
  t: Translate;
}

function TargetRows({ tags, targets, onChange, onRemove, t }: TargetsTableProps) {
  return (
    <tbody>
      {tags.map((tag) => (
        <TargetEditorRow
          key={tag}
          tag={tag}
          policy={targets[tag]}
          errors={validateTarget(targets[tag])}
          onChange={onChange}
          onRemove={onRemove}
          t={t}
        />
      ))}
    </tbody>
  );
}

function TargetsTable(props: TargetsTableProps) {
  return (
    <div className="table-scroll">
      <table className="loops-table" data-testid="draft-targets-table">
        <TableHeader t={props.t} />
        <TargetRows {...props} />
      </table>
    </div>
  );
}

export function DraftTargetsTable({ targets, onChange, t }: DraftTargetsTableProps) {
  const tags = Object.keys(targets).sort();
  const handleTargetChange = (tag: string, updated: TargetPolicy) => onChange({ ...targets, [tag]: updated });
  const handleRemove = (tag: string) => {
    const copy = { ...targets };
    delete copy[tag];
    onChange(copy);
  };

  return (
    <div data-testid="draft-targets-container">
      <AddTargetBar existingTags={tags} onAdd={(tg) => onChange({ ...targets, [tg]: { ...DEFAULT_TARGET_TEMPLATE } })} t={t} />
      <ZeroTargetsAlert count={tags.length} t={t} />
      <TargetsTable tags={tags} targets={targets} onChange={handleTargetChange} onRemove={handleRemove} t={t} />
    </div>
  );
}
