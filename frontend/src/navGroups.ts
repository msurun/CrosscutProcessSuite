// Menu groups of the console (docs/design/screens.md, "Navigation map", #172): the top-level menu shows
// groups, and a group with more than one view shows its views as a second row. Hash routes stay per view.

import type { AuthStatus } from "./AuthContext";
import type { View } from "./route";

/** The existing Anomalies entry opens equipment first; free-tag PCA remains advanced. */
export const ANOMALY_TABS = ["equipment", "advanced"] as const;

/** A top-level menu entry and the views it holds, in display order. */
export interface NavGroup {
  id: string;
  views: readonly View[];
}

export const NAV_GROUPS: readonly NavGroup[] = [
  { id: "overview", views: ["overview"] },
  { id: "trends", views: ["trends"] },
  { id: "loops", views: ["loops", "steps", "tuning"] },
  { id: "anomalies", views: ["anomalies"] },
  { id: "softsensor", views: ["softsensor"] },
  { id: "fuzzy", views: ["fuzzy", "advisory"] },
  { id: "controllers", views: ["controllers"] },
  { id: "site", views: ["catalogue", "import", "onboarding"] },
  { id: "admin", views: ["gateway", "runtime", "health", "users"] },
];

/** The groups with at least one visible view, each reduced to its visible views. */
export function visibleGroups(visible: readonly View[]): NavGroup[] {
  return NAV_GROUPS.map((group) => ({ id: group.id, views: group.views.filter((v) => visible.includes(v)) }))
    .filter((group) => group.views.length > 0);
}

/** The group that holds `view`, or undefined when no group does. */
export function groupOf(view: View, groups: readonly NavGroup[]): NavGroup | undefined {
  return groups.find((group) => group.views.includes(view));
}

/** Label key of a group: a single-view group uses its view's label. */
export function groupLabelKey(group: NavGroup): string {
  return group.views.length === 1 ? `nav.${group.views[0]}` : `nav.group.${group.id}`;
}

/**
 * Permissions that open a view (any one suffices), the menu following the roles of ADR 013. Most views read with
 * data.view like their backend GET; the engineering views ask for the permission of their main action
 * (config.edit, data.import, job.manage, users.manage) so an operator's menu stays short. No permission is changed.
 */
export const VIEW_PERMISSIONS: Readonly<Record<View, readonly string[]>> = {
  overview: ["data.view"],
  trends: ["data.view"],
  loops: ["data.view"],
  steps: ["data.view"],
  tuning: ["gw.view"],
  anomalies: ["config.edit"],
  softsensor: ["config.edit"],
  fuzzy: ["config.edit"],
  advisory: ["config.edit"],
  controllers: ["ctl.view"],
  catalogue: ["config.edit"],
  import: ["data.import"],
  onboarding: ["config.edit"],
  gateway: ["gw.view"],
  runtime: ["job.manage"],
  users: ["users.manage"],
  health: ["job.manage"],
};

/** Every view the menu knows, in menu order. */
const ALL_VIEWS: readonly View[] = NAV_GROUPS.flatMap((group) => group.views);

/** True when a session may open `view`; auth off shows everything except Users, which needs a signed-in manager. */
export function canOpenView(view: View, status: AuthStatus, permissions: readonly string[]): boolean {
  if (status === "disabled") return view !== "users";
  if (status !== "authenticated") return false;
  return VIEW_PERMISSIONS[view].some((permission) => permissions.includes(permission));
}

/** The views offered to a session. */
export function visibleViews(status: AuthStatus, permissions: readonly string[]): View[] {
  return ALL_VIEWS.filter((view) => canOpenView(view, status, permissions));
}
