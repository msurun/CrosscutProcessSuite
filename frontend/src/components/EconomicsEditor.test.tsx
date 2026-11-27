// frontend/src/components/EconomicsEditor.test.tsx
/**
 * Unit tests of the economics editor: render with units, save payload without empty fields,
 * reset to the catalogue, the forbidden state and API errors shown as alerts.
 */

import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import * as api from "../controllersApi";
import type { ControllerDetail } from "../controllersApi";
import { mockT } from "../tuningTestKit";
import { EconomicsEditor } from "./EconomicsEditor";

const variable = (id: string, role: string) => ({ id, role }) as ControllerDetail["variables"][number];
const detail = {
  id: "M1",
  variables: [variable("sump", "CV"), variable("feed", "MV")],
  economics: { currency: "EUR", cv_value: { sump: 2 }, mv_cost: {}, soft_limits: { sump: { hi: 0.8 } }, source: "catalogue" },
} as unknown as ControllerDetail;

afterEach(() => vi.restoreAllMocks());

describe("EconomicsEditor", () => {
  it("renders values with the unit in the headers and the source", () => {
    render(<EconomicsEditor detail={detail} canEdit onSaved={() => undefined} t={mockT} />);
    expect(screen.getByTestId("economics-cvs").textContent).toContain('"unit":"EUR/h"');
    expect((screen.getByLabelText(/sump: .*col\.value/) as HTMLInputElement).value).toBe("2");
    expect(screen.getByTestId("economics-source").textContent).toContain("source.catalogue");
  });

  it("saves a payload that omits empty fields", async () => {
    const put = vi.spyOn(api, "putControllerEconomics").mockResolvedValue(detail);
    const saved = vi.fn();
    render(<EconomicsEditor detail={detail} canEdit onSaved={saved} t={mockT} />);
    fireEvent.change(screen.getByLabelText(/feed: .*col\.cost/), { target: { value: "0.5" } });
    fireEvent.click(screen.getByTestId("economics-save"));
    await waitFor(() => expect(saved).toHaveBeenCalledWith(detail));
    expect(put).toHaveBeenCalledWith("M1", {
      currency: "EUR", cv_value: { sump: 2 }, mv_cost: { feed: 0.5 }, soft_limits: { sump: { hi: 0.8 } },
    });
  });

  it("resets to the catalogue", async () => {
    const del = vi.spyOn(api, "deleteControllerEconomics").mockResolvedValue(detail);
    render(<EconomicsEditor detail={detail} canEdit onSaved={() => undefined} t={mockT} />);
    fireEvent.click(screen.getByTestId("economics-reset"));
    await waitFor(() => expect(del).toHaveBeenCalledWith("M1"));
  });

  it("is disabled with a note without config.edit", () => {
    render(<EconomicsEditor detail={detail} canEdit={false} onSaved={() => undefined} t={mockT} />);
    expect(screen.getByTestId("economics-forbidden")).toBeTruthy();
    expect((screen.getByTestId("economics-save") as HTMLButtonElement).disabled).toBe(true);
    expect((screen.getByTestId("economics-reset") as HTMLButtonElement).disabled).toBe(true);
  });

  it("shows an API refusal as an alert", async () => {
    vi.spyOn(api, "putControllerEconomics").mockRejectedValue(new api.ControllersApiError(422, ["cv_value: bad"]));
    render(<EconomicsEditor detail={detail} canEdit onSaved={() => undefined} t={mockT} />);
    fireEvent.click(screen.getByTestId("economics-save"));
    expect((await screen.findByRole("alert")).textContent).toContain("cv_value: bad");
  });
});
