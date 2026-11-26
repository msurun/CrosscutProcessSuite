// Read-only display of the settings a whole-file import will use (GET /site/import-settings): the
// site's values over the defaults. They are edited in the Site view, never here.
import { useEffect, useState } from "react";
import { ApiError, fetchImportSettings, type ImportSettings as Settings } from "../api";
import type { Translate } from "../findings";

type Load = { state: "loading" } | { state: "missing" } | { state: "failed"; reason: string } | { state: "ok"; settings: Settings };

/** Loads the settings once; a 404 means the site has no file yet. */
function useImportSettings(): Load {
  const [load, setLoad] = useState<Load>({ state: "loading" });
  useEffect(() => {
    let current = true;
    fetchImportSettings()
      .then((settings) => { if (current) setLoad({ state: "ok", settings }); })
      .catch((failure: unknown) => {
        if (!current) return;
        const missing = failure instanceof ApiError && failure.status === 404;
        setLoad(missing ? { state: "missing" } : { state: "failed", reason: failure instanceof Error ? failure.message : String(failure) });
      });
    return () => { current = false; };
  }, []);
  return load;
}

/** One term and its value of the settings list. */
function Row({ label, value }: { label: string; value: string }) {
  return (
    <>
      <dt>{label}</dt>
      <dd>{value}</dd>
    </>
  );
}

/** The import settings as a definition list, with a note where they come from. */
export function ImportSettings({ t }: { t: Translate }) {
  const load = useImportSettings();
  if (load.state === "loading") return null;
  return (
    <section aria-label={t("import.settings.title")} data-testid="import-settings">
      <h3>{t("import.settings.title")}</h3>
      {load.state === "missing" && <p className="hint">{t("import.settings.missing")}</p>}
      {load.state === "failed" && <p className="status">{t("import.settings.failed", { reason: load.reason })}</p>}
      {load.state === "ok" && (
        <>
          <p className="hint">{t("import.settings.hint")}</p>
          <dl className="settings-list">
            <Row label={t("import.settings.delimiter")} value={JSON.stringify(load.settings.delimiter)} />
            <Row label={t("import.settings.decimalComma")} value={load.settings.decimal_comma ? t("import.settings.yes") : t("import.settings.no")} />
            <Row label={t("import.settings.missingCodes")} value={load.settings.missing_codes.length > 0 ? load.settings.missing_codes.join(", ") : t("import.settings.noneSet")} />
            <Row label={t("import.settings.timeNames")} value={load.settings.time_names.join(", ")} />
          </dl>
        </>
      )}
    </section>
  );
}
