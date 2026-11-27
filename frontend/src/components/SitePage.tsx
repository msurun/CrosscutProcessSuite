// src/components/SitePage.tsx
/**
 * Site catalogue page view for the plant site document (Phase 1, #36, #37, #43).
 * Embeds the schema-driven ConfigEditorPage for kind "site" and fixed id "site",
 * provides the interactive CatalogueWizard for role mapping, and the SourcesPanel
 * for connector testing and live browsing.
 */

import { useState, type ReactElement } from "react";
import type { Translate } from "../findings";
import { ConfigEditorPage } from "../ConfigEditorPage";
import { CatalogueWizard } from "./CatalogueWizard";
import { SourcesPanel } from "./SourcesPanel";
import { CatalogueFromSource } from "./CatalogueFromSource";
import { SourceAdminPanel } from "./SourceAdminPanel";
import { EquipmentEditor } from "./EquipmentEditor";
import { ModeProposals } from "./ModeProposals";

export interface SitePageProps {
  /** Translation function for localized UI strings. */
  t: Translate;
}

/**
 * Renders the site catalogue editor page with a toggle between Direct Editor, Mapping Wizard, and Sources.
 *
 * In plain words:
 * The site configuration document (`site.json`) unites physical tag definitions,
 * equipment hierarchies, PID loops, and module roles. Users can directly edit the
 * JSON schema form, walk through the mapping wizard, or test connector sources.
 */
export function SitePage({ t }: SitePageProps): ReactElement {
  const [mode, setMode] = useState<"editor" | "wizard" | "sources" | "fromSource" | "equipment" | "modes">("editor");

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
        <button
          type="button"
          className={`filter-chip ${mode === "sources" ? "filter-chip-active" : ""}`}
          data-testid="mode-data-sources"
          onClick={() => setMode("sources")}
        >
          {t("catalogue.wizard.switchSources")}
        </button>
        <button
          type="button"
          className={`filter-chip ${mode === "fromSource" ? "filter-chip-active" : ""}`}
          data-testid="mode-from-source"
          onClick={() => setMode("fromSource")}
        >
          {t("catalogueSource.tab")}
        </button>
        <button
          type="button"
          className={`filter-chip ${mode === "equipment" ? "filter-chip-active" : ""}`}
          data-testid="mode-equipment"
          onClick={() => setMode("equipment")}
        >
          {t("equipment.tab")}
        </button>
        <button
          type="button"
          className={`filter-chip ${mode === "modes" ? "filter-chip-active" : ""}`}
          data-testid="mode-proposals"
          onClick={() => setMode("modes")}
        >
          {t("modeProposal.tab")}
        </button>
      </div>

      {mode === "wizard" && <CatalogueWizard t={t} onClose={() => setMode("editor")} />}
      {mode === "sources" && (
        <>
          <SourceAdminPanel t={t} />
          <SourcesPanel t={t} />
        </>
      )}
      {mode === "equipment" && <EquipmentEditor t={t} />}
      {mode === "modes" && <ModeProposals t={t} />}
      {mode === "fromSource" && <CatalogueFromSource t={t} />}
      {mode === "editor" && <ConfigEditorPage kind="site" configId="site" t={t} />}
    </section>
  );
}
