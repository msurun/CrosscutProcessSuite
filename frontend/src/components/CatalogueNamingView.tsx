// Result view of the naming rules (#209): counts, loops table, incomplete loops, conflicts, unmatched tags, tree.
// Pure display of a NamingResult; the wizard owns the data and the checkboxes.
import type { ReactElement } from "react";

import type { NamingResult } from "../catalogueSourceApi";
import type { Translate } from "../findings";

const ROLES = ["pv", "sp", "out", "mode"] as const;

function LoopsTable({ t, result }: { t: Translate; result: NamingResult }): ReactElement | null {
  const missing = new Map(result.incomplete.map((i) => [i.loop, i.missing]));
  const ids = Object.keys(result.loops);
  if (ids.length === 0) return null;
  return (
    <table aria-label={t("catalogueSource.loops")}>
      <thead>
        <tr>
          <th>{t("catalogueSource.loop")}</th>
          {ROLES.map((r) => <th key={r}>{r.toUpperCase()}</th>)}
        </tr>
      </thead>
      <tbody>
        {ids.map((id) => (
          <tr key={id} data-testid={`loop-${id}`}>
            <td>{id}</td>
            {ROLES.map((role) => {
              const gap = missing.get(id)?.includes(role) ?? false;
              return (
                <td key={role} data-missing={gap || undefined} style={gap ? { background: "#fdd" } : undefined}>
                  {result.loops[id][role] ?? (gap ? t("catalogueSource.missing") : "")}
                </td>
              );
            })}
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function Tree({ t, result }: { t: Translate; result: NamingResult }): ReactElement {
  return (
    <ul aria-label={t("catalogueSource.tree")}>
      {Object.entries(result.tree).map(([area, equipment]) => (
        <li key={area}>
          {area || t("catalogueSource.noArea")}
          <ul>
            {Object.entries(equipment).map(([name, node]) => (
              <li key={name}>
                {name || t("catalogueSource.noEquipment")}
                {" "}({t("catalogueSource.loopsAndSignals", { loops: node.loops.join(", "), signals: node.signals.join(", ") })})
              </li>
            ))}
          </ul>
        </li>
      ))}
    </ul>
  );
}

/** Counts and every problem list of one naming result. */
export function CatalogueNamingView({ t, result }: { t: Translate; result: NamingResult }): ReactElement {
  return (
    <div>
      <p>
        {t("catalogueSource.counts", {
          matched: result.matches.length,
          unmatched: result.unmatched.length,
          loops: Object.keys(result.loops).length,
        })}
      </p>
      <LoopsTable t={t} result={result} />
      {result.incomplete.length > 0 && (
        <ul aria-label={t("catalogueSource.incomplete")}>
          {result.incomplete.map((i) => (
            <li key={i.loop}>{t("catalogueSource.incompleteLoop", { loop: i.loop, missing: i.missing.join(", ") })}</li>
          ))}
        </ul>
      )}
      {result.conflicts.length > 0 && (
        <ul aria-label={t("catalogueSource.conflicts")}>
          {result.conflicts.map((c, i) => <li key={i}>{JSON.stringify(c)}</li>)}
        </ul>
      )}
      {result.unmatched.length > 0 && (
        <details>
          <summary>{t("catalogueSource.unmatched")} ({result.unmatched.length})</summary>
          <ul>{result.unmatched.map((tag) => <li key={tag}>{tag}</li>)}</ul>
        </details>
      )}
      <Tree t={t} result={result} />
    </div>
  );
}
