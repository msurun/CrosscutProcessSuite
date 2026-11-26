// Menu groups of the console (docs/design/screens.md, "Navigation map", #172): the top-level menu shows
// groups, and a group with more than one view shows its views as a second row. Hash routes stay per view.

import type { View } from "./route";

/** The existing Anomalies entry opens equipment first; free-tag PCA remains advanced. */
export const ANOMALY_TABS = ["equipment", "advanced"] as const;

/** A top-level menu entry and the views it holds, in display order. */
export interface NavGroup {
  id: string;
  views: readonly View[];
}

export const NAV_GROUPS: readonly NavGroup[] = [
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
