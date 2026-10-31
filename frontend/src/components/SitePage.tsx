// src/components/SitePage.tsx
/**
 * Site catalogue page view for the plant site document (Phase 1, #36 exit criterion).
 * Embeds the schema-driven ConfigEditorPage for kind "site" and fixed id "site",
 * enabling the process engineer to view and edit plant equipment, tags, loops, and modes.
 */

import type { ReactElement } from "react";
import type { Translate } from "../findings";
import { ConfigEditorPage } from "../ConfigEditorPage";

export interface SitePageProps {
  /** Translation function for localized UI strings. */
  t: Translate;
}

/**
 * Renders the site catalogue editor page using the schema-driven form renderer.
 *
 * In plain words:
 * The site configuration document (`site.json`) is the plant-wide catalogue
 * that unites physical tag definitions, equipment hierarchies, PID loops,
 * and operating mode rules. The backend API enforces fixed kind "site" and id "site".
 */
export function SitePage({ t }: SitePageProps): ReactElement {
  return (
    <section className="site-page" aria-label={t("nav.catalogue")}>
      <ConfigEditorPage kind="site" configId="site" t={t} />
    </section>
  );
}

