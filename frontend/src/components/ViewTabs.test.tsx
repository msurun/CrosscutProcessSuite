// frontend/src/components/ViewTabs.test.tsx
// The Tuning tab needs gw.view; the Users tab needs users.manage.

import { cleanup, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { mockT, renderAs } from "../tuningTestKit";
import { ViewTabs } from "./ViewTabs";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const tabs = <nav data-testid="tabs-ready"><ViewTabs view="trends" onSelect={() => undefined} t={mockT} /></nav>;

describe("ViewTabs", () => {
  it.each(["viewer", "operator", "engineer", "lead", "off"])("shows the tuning tab for %s", async (role) => {
    await renderAs(role, tabs, role, "tabs-ready");
    expect(screen.getByRole("button", { name: "nav.tuning" })).toBeInTheDocument();
  });

  it("hides the tuning tab for a role without gw.view", async () => {
    await renderAs("service", tabs, "svc", "tabs-ready");
    expect(screen.queryByRole("button", { name: "nav.tuning" })).toBeNull();
  });
});
