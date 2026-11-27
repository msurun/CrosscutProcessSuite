// Menu groups (#172): every view sits in exactly one group, hidden views drop out, labels follow group size.

import { describe, expect, it } from "vitest";
import { DEFAULT_ROLE_PERMISSIONS } from "./AuthContext";
import { canOpenView, groupLabelKey, groupOf, NAV_GROUPS, visibleGroups, visibleViews } from "./navGroups";
import type { View } from "./route";

const ALL: View[] = [
  "overview", "trends", "loops", "fuzzy", "advisory", "anomalies", "softsensor", "steps", "import",
  "catalogue", "onboarding", "runtime", "controllers", "gateway", "health", "tuning", "users", "backup", "dependencies",
];

describe("navGroups", () => {
  it("offers Overview first and keeps Trends reachable", () => {
    expect(NAV_GROUPS[0]).toEqual({ id: "overview", views: ["overview"] });
    expect(groupOf("trends", NAV_GROUPS)?.id).toBe("trends");
  });
  it("puts every view in exactly one group", () => {
    for (const view of ALL) {
      expect(NAV_GROUPS.filter((g) => g.views.includes(view))).toHaveLength(1);
    }
  });

  it("drops hidden views and empty groups", () => {
    const groups = visibleGroups(ALL.filter((v) => v !== "controllers" && v !== "users"));
    expect(groups.map((g) => g.id)).not.toContain("controllers");
    expect(groupOf("gateway", groups)?.views).toEqual(["gateway", "runtime", "health", "backup"]);
  });

  it("labels a single-view group by its view and a multi-view group by its id", () => {
    const groups = visibleGroups(ALL);
    expect(groupLabelKey(groupOf("trends", groups)!)).toBe("nav.trends");
    expect(groupLabelKey(groupOf("advisory", groups)!)).toBe("nav.group.fuzzy");
  });
});

const menu = (role: string) => visibleGroups(visibleViews("authenticated", DEFAULT_ROLE_PERMISSIONS[role])).map((g) => g.id);

describe("role-based menu (#175)", () => {
  it("shows an operator Overview, Trends, Loops, Controllers and the approval queue only", () => {
    expect(menu("operator")).toEqual(["overview", "trends", "loops", "controllers", "admin"]);
    const groups = visibleGroups(visibleViews("authenticated", DEFAULT_ROLE_PERMISSIONS.operator));
    expect(groupLabelKey(groupOf("gateway", groups)!)).toBe("nav.gateway");
    expect(canOpenView("catalogue", "authenticated", DEFAULT_ROLE_PERMISSIONS.operator)).toBe(false);
    expect(canOpenView("users", "authenticated", DEFAULT_ROLE_PERMISSIONS.operator)).toBe(false);
  });

  it.each(["engineer", "lead"])("shows %s Site and Administration", (role) => {
    expect(menu(role)).toEqual(expect.arrayContaining(["site", "admin", "anomalies", "fuzzy", "controllers"]));
    const groups = visibleGroups(visibleViews("authenticated", DEFAULT_ROLE_PERMISSIONS[role]));
    expect(groupOf("gateway", groups)?.views).toEqual(["gateway", "runtime", "health"]);
  });

  it("shows the administrator the user page and no engineering views", () => {
    const views = visibleViews("authenticated", DEFAULT_ROLE_PERMISSIONS.admin);
    expect(views).toContain("users");
    expect(views).not.toContain("catalogue");
  });

  it("shows everything but Users when auth is off, nothing when signed out", () => {
    expect(visibleViews("disabled", [])).toHaveLength(ALL.length - 1);
    expect(visibleViews("anonymous", ["data.view"])).toEqual([]);
  });
});
