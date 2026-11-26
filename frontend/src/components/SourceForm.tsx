// Form to add or edit one source (issue #208): driver fields, authentication, secret, test and save.
// The secret is typed into a password field, sent only to the secret route after the save, then cleared.
import { useEffect, useState, type ReactElement } from "react";

import type { Translate } from "../findings";
import {
  fetchSecretStored,
  putSecret,
  saveSource,
  testDraft,
  type AuthKind,
  type SourceDriver,
  type SourceEntry,
  type SourceTestReport,
} from "../sourceAdminApi";

export interface SourceFormProps {
  t: Translate;
  /** The source to edit; omitted when adding a new one. */
  initial?: SourceEntry;
  onSaved: (entry: SourceEntry) => void;
  onCancel: () => void;
}

const DRIVERS: SourceDriver[] = ["csv", "opcua", "sql", "pi", "piwebapi"];
const PROFILES = ["aspen_ip21", "aveva_wonderware", "honeywell_phd", "siemens_wincc"];
const NEEDS_SECRET: (AuthKind | "")[] = ["basic", "bearer"];

type FieldKey = "endpoint" | "base_url" | "data_server" | "profile";
type Setter = (key: FieldKey, value: string) => void;

/** Remove empty values so the saved entry holds only what the person filled in. */
export function cleanEntry(entry: SourceEntry, secret: boolean): SourceEntry {
  const out: SourceEntry = { id: entry.id.trim(), driver: entry.driver };
  for (const key of ["endpoint", "base_url", "data_server", "web_id", "profile"] as const) {
    const value = entry[key]?.trim();
    if (value) out[key] = value;
  }
  if (entry.auth) {
    const { kind, credential_env, credential_ref } = entry.auth;
    const ref = credential_ref || (secret && !credential_env ? `source.${out.id}` : undefined);
    out.auth = { kind, ...(credential_env ? { credential_env } : {}), ...(ref ? { credential_ref: ref } : {}) };
  }
  return out;
}

function TextField(props: { label: string; name: FieldKey; value?: string; onChange: Setter }): ReactElement {
  const { label, name, value, onChange } = props;
  return (
    <label className="field">
      {label}
      <input type="text" value={value ?? ""} onChange={(e) => onChange(name, e.target.value)} />
    </label>
  );
}

function DriverFields(props: { t: Translate; entry: SourceEntry; set: Setter }): ReactElement {
  const { t, entry, set } = props;
  if (entry.driver === "piwebapi") {
    return (
      <>
        <TextField label={t("sources.baseUrl")} name="base_url" value={entry.base_url} onChange={set} />
        <TextField label={t("sources.dataServer")} name="data_server" value={entry.data_server} onChange={set} />
      </>
    );
  }
  return (
    <>
      <TextField label={t("sources.endpoint")} name="endpoint" value={entry.endpoint} onChange={set} />
      {entry.driver === "sql" && (
        <label className="field">
          {t("sources.profile")}
          <select value={entry.profile ?? ""} onChange={(e) => set("profile", e.target.value)}>
            <option value="">{t("sources.profileNone")}</option>
            {PROFILES.map((p) => (
              <option key={p} value={p}>{p}</option>
            ))}
          </select>
        </label>
      )}
    </>
  );
}

interface AuthProps {
  t: Translate;
  kind: AuthKind | "";
  stored: boolean | null;
  secret: string;
  onKind: (kind: AuthKind | "") => void;
  onSecret: (value: string) => void;
}

function AuthFields({ t, kind, stored, secret, onKind, onSecret }: AuthProps): ReactElement {
  return (
    <>
      <label className="field">
        {t("sources.authKind")}
        <select value={kind} onChange={(e) => onKind(e.target.value as AuthKind | "")}>
          <option value="">{t("sources.authNone")}</option>
          {(["basic", "kerberos", "bearer"] as const).map((k) => (
            <option key={k} value={k}>{k}</option>
          ))}
        </select>
      </label>
      {NEEDS_SECRET.includes(kind) && (
        <>
          <label className="field">
            {kind === "bearer" ? t("sources.token") : t("sources.password")}
            <input type="password" autoComplete="off" value={secret} onChange={(e) => onSecret(e.target.value)} />
          </label>
          <span role="status">{stored ? t("sources.secretStored") : t("sources.secretMissing")}</span>
        </>
      )}
    </>
  );
}

interface IdentityProps {
  t: Translate;
  entry: SourceEntry;
  locked: boolean;
  onChange: (entry: SourceEntry) => void;
}

function IdentityFields({ t, entry, locked, onChange }: IdentityProps): ReactElement {
  return (
    <>
      <label className="field">
        {t("sources.id")}
        <input type="text" value={entry.id} disabled={locked} onChange={(e) => onChange({ ...entry, id: e.target.value })} />
      </label>
      <label className="field">
        {t("sources.driver")}
        <select value={entry.driver} onChange={(e) => onChange({ ...entry, driver: e.target.value as SourceDriver })}>
          {DRIVERS.map((d) => (
            <option key={d} value={d}>{d}</option>
          ))}
        </select>
      </label>
    </>
  );
}

/** Whether a secret is stored for the source being edited (null while unknown). */
function useSecretStored(initial?: SourceEntry): [boolean | null, (v: boolean) => void] {
  const [stored, setStored] = useState<boolean | null>(null);
  useEffect(() => {
    if (initial) fetchSecretStored(initial.id).then(setStored, () => setStored(false));
  }, [initial]);
  return [stored, setStored];
}

/** Run an async action and keep its error message for display. */
function useRunner(): [string | null, (action: () => Promise<void>) => Promise<void>] {
  const [error, setError] = useState<string | null>(null);
  async function run(action: () => Promise<void>): Promise<void> {
    setError(null);
    try {
      await action();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }
  return [error, run];
}

/** The add / edit form of one source. */
export function SourceForm({ t, initial, onSaved, onCancel }: SourceFormProps): ReactElement {
  const [entry, setEntry] = useState<SourceEntry>(initial ?? { id: "", driver: "csv" });
  const [secret, setSecret] = useState("");
  const [report, setReport] = useState<SourceTestReport | null>(null);
  const [stored, setStored] = useSecretStored(initial);
  const [error, run] = useRunner();

  const set: Setter = (key, value) => setEntry((e) => ({ ...e, [key]: value }));
  const setKind = (k: AuthKind | "") => setEntry((e) => ({ ...e, auth: k ? { ...e.auth, kind: k } : undefined }));
  const test = () =>
    run(async () => {
      setReport(null);
      setReport(await testDraft(cleanEntry(entry, secret !== "")));
    });
  const save = () =>
    run(async () => {
      const value = secret;
      const saved = await saveSource(cleanEntry(entry, value !== "" || stored === true));
      setSecret("");
      if (value) await putSecret(saved.id, value);
      if (value) setStored(true);
      onSaved(saved);
    });

  return (
    <form className="source-form" aria-label={t("sources.formTitle")} onSubmit={(e) => e.preventDefault()}>
      <IdentityFields t={t} entry={entry} locked={initial !== undefined} onChange={setEntry} />
      <DriverFields t={t} entry={entry} set={set} />
      <AuthFields t={t} kind={entry.auth?.kind ?? ""} stored={stored} secret={secret} onKind={setKind} onSecret={setSecret} />
      {report && <p role="status">{t("sources.testOk", { capabilities: report.capabilities.join(", ") })}</p>}
      {error && <p role="alert" style={{ whiteSpace: "pre-line" }}>{error}</p>}
      <div className="form-actions">
        <button type="button" onClick={test}>{t("sources.test")}</button>
        <button type="button" onClick={save}>{t("sources.save")}</button>
        <button type="button" onClick={onCancel}>{t("sources.cancel")}</button>
      </div>
    </form>
  );
}
