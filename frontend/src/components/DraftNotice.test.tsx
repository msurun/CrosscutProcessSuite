import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { translate } from "../i18n";
import { DraftNotice } from "./DraftNotice";

afterEach(cleanup);

describe("DraftNotice", () => {
  it.each(["en", "pl", "es"] as const)("names the draft and the publish place in %s", (lang) => {
    const t = (key: string, params?: Record<string, string | number>) => translate(lang, key, params);
    render(<DraftNotice t={t} />);
    const text = screen.getByTestId("draft-notice").textContent ?? "";
    expect(text).not.toBe("draftNotice.saved");
    expect(text).toContain("Versions");
  });
});
