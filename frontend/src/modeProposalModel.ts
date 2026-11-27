// src/modeProposalModel.ts
//
// Pure edits of the site document for accepting mode and equipment proposals (#145).
// Mirrors the catalogue rules of site_refs.py: every referenced tag exists, every entry
// below the site has a parent, and ids stay unique.
import type { SiteDoc } from "./components/equipmentModel";
import type { EquipmentProposal, ModeClause, ModeProposal } from "./modeProposalApi";

/** The site document with `ids` added to `tags` when missing (a tag entry needs only an id). */
function withTags(site: SiteDoc, ids: string[]): SiteDoc {
  const known = new Set((site.tags ?? []).map((tag) => tag.id));
  const added = [...new Set(ids)].filter((id) => !known.has(id)).map((id) => ({ id }));
  return added.length === 0 ? site : { ...site, tags: [...(site.tags ?? []), ...added] };
}

/** The id of the site-level entry, and the document with one added when it has none. */
function withSiteRoot(site: SiteDoc): [SiteDoc, string] {
  const list = site.equipment ?? [];
  const root = list.find((entry) => entry.level === "site");
  if (root) return [site, root.id];
  return [{ ...site, equipment: [{ id: "site", level: "site" as const }, ...list] }, "site"];
}

/** True when an equipment id is already in the document. */
export function hasEquipment(site: SiteDoc, id: string): boolean {
  return (site.equipment ?? []).some((entry) => entry.id === id);
}

/** Accept an equipment group: the entry under the site root, its tags added to the tag list. */
export function acceptEquipment(site: SiteDoc, proposal: EquipmentProposal): SiteDoc {
  if (hasEquipment(site, proposal.entry.id)) return site;
  const [rooted, root] = withSiteRoot(withTags(site, proposal.entry.tags));
  const entry = { ...proposal.entry, parent: root };
  return { ...rooted, equipment: [...(rooted.equipment ?? []), entry] };
}

/** Accept a mode with the engineer's clauses; a proposed scope is accepted together with it. */
export function acceptMode(
  site: SiteDoc,
  proposal: ModeProposal,
  clauses: ModeClause[],
  group?: EquipmentProposal,
): SiteDoc {
  const base = proposal.scope_new && group ? acceptEquipment(site, group) : site;
  const tagged = withTags(base, clauses.map((clause) => clause.tag));
  const entry = { ...proposal.entry, condition: { ...proposal.entry.condition, clauses } };
  const modes = ((tagged.modes as { id: string }[] | undefined) ?? []).filter((mode) => mode.id !== entry.id);
  return { ...tagged, modes: [...modes, entry] };
}

/** Clause values as typed text -> clauses with numbers; null when any value is not a finite number. */
export function parseClauses(clauses: ModeClause[], typed: string[]): ModeClause[] | null {
  const values = typed.map((text) => (text.trim() === "" ? NaN : Number(text)));
  if (values.some((value) => !Number.isFinite(value))) return null;
  return clauses.map((clause, index) => ({ ...clause, value: values[index] }));
}

/** A window of seconds since the first sample as "h:mm:ss - h:mm:ss". */
export function formatWindow([start, end]: [number, number]): string {
  const clock = (s: number): string => {
    const total = Math.round(s);
    const pad = (n: number): string => String(n).padStart(2, "0");
    return `${Math.floor(total / 3600)}:${pad(Math.floor((total % 3600) / 60))}:${pad(total % 60)}`;
  };
  return `${clock(start)} - ${clock(end)}`;
}
