// src/components/SitePage.tsx
/**
 * Site catalogue page view for the plant site document (Phase 1, #36 and #37).
 * Embeds the schema-driven ConfigEditorPage for kind "site" and fixed id "site",
 * and provides the interactive CatalogueWizard for role and loop mapping.
 */

import { useState, type ReactElement } from "react";
import type { Translate } from "../findings";
import { ConfigEditorPage } from "../ConfigEditorPage";
import { CatalogueWizard } from "./CatalogueWizard";

export interface SitePageProps {
  /** Translation function for localized UI strings. */
  t: Translate;
}

/**
 * Renders the site catalogue editor page with a toggle between Direct Editor and Mapping Wizard.
 *
 * In plain words:
 * The site configuration document (`site.json`) unites physical tag definitions,
 * equipment hierarchies, PID loops, and module roles. Users can directly edit the
 * JSON schema form or walk through the multi-step mapping wizard.
 */
export function SitePage({ t }: SitePageProps): ReactElement {
  const [mode, setMode] = useState<"editor" | "wizard">("editor");

  return (
    <section className="site-page" aria-label={t("nav.catalogue")}>
      <div className="view-mode-bar" style={{ display: "flex", gap: "0.5rem", marginBottom: "1rem" }}>
        <button
          type="button"
          className={`filter-chip ${mode === "editor" ? "filter-chip-active" : ""}`}
          data-testid="mode-direct-editor"
          onClick={() => setMode("editor")}
        >
          {t("catalogue.wizard.switchDirect")}
        </button>
        <button
          type="button"
          className={`filter-chip ${mode === "wizard" ? "filter-chip-active" : ""}`}
          data-testid="mode-mapping-wizard"
          onClick={() => setMode("wizard")}
        >
          {t("catalogue.wizard.switchWizard")}
        </button>
      </div>

      {mode === "wizard" ? (
        <CatalogueWizard t={t} onClose={() => setMode("editor")} />
      ) : (
        <ConfigEditorPage kind="site" configId="site" t={t} />
      )}
    </section>
  );
}
