// frontend/src/components/ViewTabs.tsx
// The row of view tabs. "tuning" needs gw.view; "users" appears only for a signed-in user who may manage users.

import { useAuth, useCan } from "../AuthContext";
import type { Translate } from "../findings";
import type { View } from "../route";

const BASE_VIEWS = [
  "trends", "loops", "fuzzy", "advisory", "anomalies", "softsensor",
  "steps", "import", "catalogue", "onboarding", "runtime", "gateway",
] as const satisfies readonly View[];

export interface ViewTabsProps {
  view: View;
  onSelect: (view: View) => void;
  t: Translate;
}

/** The views offered to the current session. */
function useVisibleViews(): readonly View[] {
  const { status } = useAuth();
  const canManage = useCan("users.manage").allowed;
  const canView = useCan("gw.view").allowed;
  const tuning: readonly View[] = canView ? ["tuning"] : [];
  const users: readonly View[] = status === "authenticated" && canManage ? ["users"] : [];
  return [...BASE_VIEWS, ...tuning, ...users];
}

/** Navigation tabs of the console. */
export function ViewTabs({ view, onSelect, t }: ViewTabsProps) {
  const names = useVisibleViews();
  return (
    <nav className="view-tabs" aria-label={t("app.name")}>
      {names.map((name) => (
        <button
          key={name}
          type="button"
          className="view-tab"
          aria-current={view === name ? "page" : undefined}
          onClick={() => onSelect(name)}
        >
          {t(`nav.${name}`)}
        </button>
      ))}
    </nav>
  );
}
