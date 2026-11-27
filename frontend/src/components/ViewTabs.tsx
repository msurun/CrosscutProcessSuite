// frontend/src/components/ViewTabs.tsx
// Console navigation (#172): the main menu of view groups and, for a group with several views, the row of
// its views. Which views show follows the session's permissions (VIEW_PERMISSIONS in navGroups.ts, ADR 013).

import { useAuth } from "../AuthContext";
import type { Translate } from "../findings";
import { groupLabelKey, groupOf, visibleGroups, visibleViews, type NavGroup } from "../navGroups";
import type { View } from "../route";

export interface ViewTabsProps {
  view: View;
  onSelect: (view: View) => void;
  t: Translate;
}

/** The views offered to the current session (permission based, see navGroups). */
function useVisibleViews(): readonly View[] {
  const { status, permissions } = useAuth();
  return visibleViews(status, permissions);
}

/** Main menu: one entry per group; selecting a group opens its first view. */
export function MainNav({ view, onSelect, t }: ViewTabsProps) {
  const groups = visibleGroups(useVisibleViews());
  const current = groupOf(view, groups)?.id;
  return (
    <nav className="main-nav" aria-label={t("nav.main")}>
      {groups.map((group) => (
        <button
          key={group.id}
          type="button"
          className="main-nav-item"
          aria-current={current === group.id ? "page" : undefined}
          onClick={() => onSelect(group.views[0])}
        >
          {t(groupLabelKey(group))}
        </button>
      ))}
    </nav>
  );
}

/** The whole console navigation: main menu, then the views of the current group. */
export function ConsoleNav(props: ViewTabsProps) {
  return (
    <>
      <MainNav {...props} />
      <ViewTabs {...props} />
    </>
  );
}

/** Second row: the views of the current group, shown only when the group has more than one view. */
export function ViewTabs({ view, onSelect, t }: ViewTabsProps) {
  const group: NavGroup | undefined = groupOf(view, visibleGroups(useVisibleViews()));
  if (!group || group.views.length < 2) return null;
  return (
    <nav className="view-tabs" aria-label={t(groupLabelKey(group))}>
      {group.views.map((name) => (
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
