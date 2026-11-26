// Tests that a view without permission shows the no-access message instead of its page (#175).

import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { NoAccess } from "./ViewContent";

const t = (key: string, vars?: Record<string, string | number>) => `${key}|${vars?.view ?? ""}`;

describe("NoAccess", () => {
  it("names the view and is announced as an alert", () => {
    render(<NoAccess view="catalogue" t={t} />);
    expect(screen.getByRole("alert")).toHaveTextContent("access.denied.body|nav.catalogue|");
  });
});
