// Menu groups (#172): every view sits in exactly one group, hidden views drop out, labels follow group size.

import { describe, expect, it } from "vitest";
import { groupLabelKey, groupOf, NAV_GROUPS, visibleGroups } from "./navGroups";
import type { View } from "./route";

const ALL: View[] = [
  "trends", "loops", "fuzzy", "advisory", "anomalies", "softsensor", "steps", "import",
  "catalogue", "onboarding", "runtime", "controllers", "gateway", "tuning", "users", "backup",
];

describe("navGroups", () => {
  it("puts every view in exactly one group", () => {
    for (const view of ALL) {
      expect(NAV_GROUPS.filter((g) => g.views.includes(view))).toHaveLength(1);
    }
  });

  it("drops hidden views and empty groups", () => {
    const groups = visibleGroups(ALL.filter((v) => v !== "controllers" && v !== "users"));
    expect(groups.map((g) => g.id)).not.toContain("controllers");
    expect(groupOf("gateway", groups)?.views).toEqual(["gateway", "runtime", "backup"]);
  });

  it("labels a single-view group by its view and a multi-view group by its id", () => {
    const groups = visibleGroups(ALL);
    expect(groupLabelKey(groupOf("trends", groups)!)).toBe("nav.trends");
    expect(groupLabelKey(groupOf("advisory", groups)!)).toBe("nav.group.fuzzy");
  });
});
