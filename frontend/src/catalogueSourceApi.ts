// Client for "catalogue from a source" (#209): naming presets, the rule tester, the source preview and the import.
// Reuses getJson/sendJson from api.ts so errors are ApiError like every other call.
import { API_PREFIX, getJson, sendJson } from "./api";

/** One naming rule: a regex `pattern` with named groups; `roles` maps a matched value to a loop role. */
export interface NamingRule {
  name?: string;
  pattern: string;
  roles?: Record<string, string>;
}

/** One tag the rules recognised. */
export interface NamingMatch {
  tag: string;
  rule: number;
  loop?: string | null;
  role?: string | null;
  area?: string | null;
  equipment?: string | null;
  signal?: string | null;
}

/** A loop with roles still missing. */
export interface IncompleteLoop {
  loop: string;
  missing: string[];
}

/** Equipment content in the tree: its loops and plain signals. */
export interface EquipmentNode {
  loops: string[];
  signals: string[];
}

/** What the rules made of a list of tag names. */
export interface NamingResult {
  matches: NamingMatch[];
  unmatched: string[];
  conflicts: Record<string, unknown>[];
  loops: Record<string, Record<string, string>>;
  incomplete: IncompleteLoop[];
  tree: Record<string, Record<string, EquipmentNode>>;
}

/** A browsed variable node. */
export interface PreviewItem {
  name: string;
  address?: string;
  unit?: string | null;
  description?: string | null;
}

export interface CataloguePreview {
  items: PreviewItem[];
  truncated: boolean;
  naming: NamingResult;
}

export interface ImportCounts {
  tags: number;
  loops: number;
  equipment: number;
}

/** Built-in rule sets by name. @throws {ApiError} On a non-2xx response. */
export async function fetchNamingPresets(): Promise<Record<string, NamingRule[]>> {
  const body = await getJson<{ presets: Record<string, NamingRule[]> }>(`${API_PREFIX}/catalogue/naming/presets`);
  return body.presets;
}

/** Apply `rules` to tag names without browsing anything (instant). */
export async function testNamingRules(rules: NamingRule[], tags: string[]): Promise<NamingResult> {
  return sendJson<NamingResult>("POST", `${API_PREFIX}/catalogue/naming/test`, { rules, tags });
}

/** Browse the source (`nodes`: null = root, or branch ids) and apply the rules. */
export async function previewCatalogue(
  sourceId: string,
  rules: NamingRule[],
  nodes: (string | null)[] = [null],
): Promise<CataloguePreview> {
  const url = `${API_PREFIX}/sources/${encodeURIComponent(sourceId)}/catalogue-preview`;
  return sendJson<CataloguePreview>("POST", url, { nodes, rules });
}

export interface ImportOptions {
  loops: boolean;
  equipment: boolean;
}

/** Merge the accepted preview items into the site catalogue. */
export async function importCatalogue(
  sourceId: string,
  tags: PreviewItem[],
  rules: NamingRule[],
  options: ImportOptions,
): Promise<{ added: ImportCounts }> {
  const url = `${API_PREFIX}/sources/${encodeURIComponent(sourceId)}/catalogue-import`;
  return sendJson<{ added: ImportCounts }>("POST", url, { tags, rules, ...options });
}
