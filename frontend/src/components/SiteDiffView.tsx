// Renders a structured catalogue diff (#165): per section the added and removed ids and the changed fields.
import type { ReactElement } from "react";

import type { Translate } from "../findings";
import type { FieldChange, SiteDiff } from "../siteVersionsApi";

const show = (value: unknown): string => (value === undefined ? "-" : JSON.stringify(value));

function FieldList({ fields }: { fields: FieldChange[] }): ReactElement {
  return (
    <ul>
      {fields.map((f) => (
        <li key={f.field}>
          <code>{f.field || "."}</code>: {show(f.before)} {"→"} {show(f.after)}
        </li>
      ))}
    </ul>
  );
}

export interface SiteDiffViewProps {
  diff: SiteDiff;
  t: Translate;
}

/** The diff as nested lists; an empty diff says so. */
export function SiteDiffView({ diff, t }: SiteDiffViewProps): ReactElement {
  if (diff.empty) return <p>{t("versions.noChanges")}</p>;
  return (
    <div className="site-diff" data-testid="site-diff">
      {Object.entries(diff.sections).map(([name, s]) => (
        <section key={name} aria-label={name}>
          <h4>{name}</h4>
          {s.added?.length ? <p>{t("versions.added", { ids: s.added.join(", ") })}</p> : null}
          {s.removed?.length ? <p>{t("versions.removed", { ids: s.removed.join(", ") })}</p> : null}
          {s.changed?.map((c) => (
            <div key={c.id}>
              <strong>{c.id}</strong>
              <FieldList fields={c.fields} />
            </div>
          ))}
          {s.fields ? <FieldList fields={s.fields} /> : null}
        </section>
      ))}
    </div>
  );
}
