// Component tests of the read-only import settings of the Import view: values shown, the no-site-file
// note on 404 and the failure note. fetch is mocked.
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { translate } from "../i18n";
import { ImportSettings } from "./ImportSettings";

const t = (key: string, params?: Record<string, string | number>) => translate("en", key, params);

function stub(status: number, body: unknown): void {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify(body), { status })));
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("ImportSettings", () => {
  it("lists the settings read-only", async () => {
    stub(200, { missing_codes: [-9999, -1], decimal_comma: true, delimiter: ";", time_names: ["time", "timestamp"] });
    render(<ImportSettings t={t} />);
    expect(await screen.findByText("-9999, -1")).toBeInTheDocument();
    expect(screen.getByText('";"')).toBeInTheDocument();
    expect(screen.getByText("time, timestamp")).toBeInTheDocument();
    expect(screen.getByText("yes")).toBeInTheDocument();
    expect(screen.queryByRole("textbox")).toBeNull();
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("says the defaults apply when there is no site file (404)", async () => {
    stub(404, { detail: "no site file" });
    render(<ImportSettings t={t} />);
    expect(await screen.findByText(/no site file yet/)).toBeInTheDocument();
  });

  it("shows a quiet failure note for other errors", async () => {
    stub(500, { detail: "boom" });
    render(<ImportSettings t={t} />);
    expect(await screen.findByText(/could not be read: boom/)).toBeInTheDocument();
  });
});
