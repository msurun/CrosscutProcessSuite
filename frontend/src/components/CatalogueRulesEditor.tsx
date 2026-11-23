// Naming-rule editor of the "catalogue from a source" wizard (#209): preset select and a list of rules.
// A rule is edited as text (pattern, name, roles as "value=role" lines) and converted to a NamingRule on use.
import type { ReactElement } from "react";

import type { NamingRule } from "../catalogueSourceApi";
import type { Translate } from "../findings";

/** A rule as typed: roles stay one text block until the rules are used. */
export interface RuleDraft {
  name: string;
  pattern: string;
  rolesText: string;
}

export const EMPTY_RULE: RuleDraft = { name: "", pattern: "", rolesText: "" };

/** Parse "value=role" lines; blank lines and lines without "=" are skipped. */
export function parseRoles(text: string): Record<string, string> {
  const roles: Record<string, string> = {};
  for (const line of text.split("\n")) {
    const at = line.indexOf("=");
    if (at > 0 && line.slice(at + 1).trim()) roles[line.slice(0, at).trim()] = line.slice(at + 1).trim();
  }
  return roles;
}

/** The API rule of a draft; empty name and roles are left out. */
export function draftToRule(draft: RuleDraft): NamingRule {
  const rule: NamingRule = { pattern: draft.pattern };
  if (draft.name.trim()) rule.name = draft.name.trim();
  const roles = parseRoles(draft.rolesText);
  if (Object.keys(roles).length > 0) rule.roles = roles;
  return rule;
}

/** The draft of an API rule (a preset). */
export function ruleToDraft(rule: NamingRule): RuleDraft {
  const lines = Object.entries(rule.roles ?? {}).map(([value, role]) => `${value}=${role}`);
  return { name: rule.name ?? "", pattern: rule.pattern, rolesText: lines.join("\n") };
}

/** Move item `from` to `to` in a copy of the list (out-of-range moves return the list unchanged). */
export function moveItem<T>(list: T[], from: number, to: number): T[] {
  if (to < 0 || to >= list.length) return list;
  const copy = [...list];
  copy.splice(to, 0, copy.splice(from, 1)[0]);
  return copy;
}

interface RowProps {
  t: Translate;
  index: number;
  count: number;
  rule: RuleDraft;
  onChange: (rule: RuleDraft) => void;
  onMove: (to: number) => void;
  onRemove: () => void;
}

function RuleRow({ t, index, count, rule, onChange, onMove, onRemove }: RowProps): ReactElement {
  const label = (key: string) => `${t(key)} ${index + 1}`;
  return (
    <li data-testid="catalogue-rule">
      <input aria-label={label("catalogueSource.rulePattern")} value={rule.pattern}
        onChange={(e) => onChange({ ...rule, pattern: e.target.value })} />
      <input aria-label={label("catalogueSource.ruleName")} value={rule.name}
        onChange={(e) => onChange({ ...rule, name: e.target.value })} />
      <textarea aria-label={label("catalogueSource.ruleRoles")} rows={2} value={rule.rolesText}
        onChange={(e) => onChange({ ...rule, rolesText: e.target.value })} />
      <button type="button" disabled={index === 0} aria-label={label("catalogueSource.ruleUp")}
        onClick={() => onMove(index - 1)}>↑</button>
      <button type="button" disabled={index === count - 1} aria-label={label("catalogueSource.ruleDown")}
        onClick={() => onMove(index + 1)}>↓</button>
      <button type="button" aria-label={label("catalogueSource.ruleRemove")} onClick={onRemove}>×</button>
    </li>
  );
}

export interface CatalogueRulesEditorProps {
  t: Translate;
  presets: Record<string, NamingRule[]>;
  rules: RuleDraft[];
  onChange: (rules: RuleDraft[]) => void;
}

/** Preset select, the ordered rule list and an Add button. */
export function CatalogueRulesEditor({ t, presets, rules, onChange }: CatalogueRulesEditorProps): ReactElement {
  const replaceAt = (i: number, rule: RuleDraft) => onChange(rules.map((r, j) => (j === i ? rule : r)));
  const pickPreset = (name: string) => name && onChange((presets[name] ?? []).map(ruleToDraft));
  return (
    <div>
      <label>
        {t("catalogueSource.preset")}
        <select value="" onChange={(e) => pickPreset(e.target.value)}>
          <option value="">{t("catalogueSource.presetNone")}</option>
          {Object.keys(presets).map((name) => <option key={name} value={name}>{name}</option>)}
        </select>
      </label>
      <p>{t("catalogueSource.rolesHint")}</p>
      <ol>
        {rules.map((rule, i) => (
          <RuleRow key={i} t={t} index={i} count={rules.length} rule={rule}
            onChange={(r) => replaceAt(i, r)} onMove={(to) => onChange(moveItem(rules, i, to))}
            onRemove={() => onChange(rules.filter((_, j) => j !== i))} />
        ))}
      </ol>
      <button type="button" onClick={() => onChange([...rules, EMPTY_RULE])}>{t("catalogueSource.addRule")}</button>
    </div>
  );
}
