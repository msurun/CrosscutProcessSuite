// Tests of the equipment hierarchy editor (#214): tree, edits, confirm all, delete guard, save and 422.
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import * as api from "../api";
import { translate } from "../i18n";
import { EquipmentEditor } from "./EquipmentEditor";
import { addEntry, removeEntry, type Equipment } from "./equipmentModel";

const t = (key: string, params?: Record<string, string | number>) => translate("en", key, params);

const SITE = {
  schema_version: 1,
  tags: [{ id: "T1" }, { id: "T2" }],
  loops: [{ id: "L1" }, { id: "L2" }],
  equipment: [
    { id: "s", level: "site", name: "Plant" },
    { id: "a", level: "area", parent: "s", name: "Area A" },
    { id: "u", level: "unit", parent: "a", name: "Unit U" },
    {
      id: "m", level: "equipment", parent: "u", name: "Mill", loops: ["L1"],
      signals: [{ tag: "T1", kind: "current", confirmed: false }],
      running: { tag: "T1", above: 5, confirmed: false },
    },
  ],
};

beforeEach(() => {
  vi.spyOn(api, "getJson").mockResolvedValue(structuredClone(SITE));
});
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("equipment model", () => {
  it("refuses to delete an entry with children and adds under a valid parent", () => {
    const list = SITE.equipment as Equipment[];
    expect(removeEntry(list, "a")).toBeNull();
    expect(addEntry(list, "equipment", "a")?.at(-1)?.parent).toBe("a");
    expect(addEntry([], "area")).toBeNull();
  });
});

describe("EquipmentEditor", () => {
  it("shows counts and the unconfirmed badge, and confirm all clears it", async () => {
    render(<EquipmentEditor t={t} />);
    await screen.findByTestId("eq-m");
    expect(screen.getByText("1 loops, 1 signals")).toBeTruthy();
    expect(screen.getByText("2 unconfirmed")).toBeTruthy();
    fireEvent.click(screen.getByText("Confirm all proposals"));
    expect(screen.queryByText("2 unconfirmed")).toBeNull();
    expect(screen.getByRole("status").textContent).toBe("You have unsaved changes.");
  });

  it("collapses a branch", async () => {
    render(<EquipmentEditor t={t} />);
    await screen.findByTestId("eq-m");
    fireEvent.click(screen.getByLabelText("Expand or collapse a"));
    expect(screen.queryByTestId("eq-u")).toBeNull();
  });

  it("refuses to delete an entry with children", async () => {
    render(<EquipmentEditor t={t} />);
    fireEvent.click(await screen.findByTestId("eq-a"));
    fireEvent.click(screen.getByText("Delete entry"));
    expect((await screen.findByRole("alert")).textContent).toContain("still has children");
  });

  it("saves the whole edited site and shows 422 problems", async () => {
    const put = vi.spyOn(api, "sendJson").mockRejectedValueOnce(new api.ApiError(422, "loop L1 owned twice"));
    render(<EquipmentEditor t={t} />);
    fireEvent.click(await screen.findByTestId("eq-m"));
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Ball mill" } });
    fireEvent.click(screen.getByText("Save equipment"));
    expect((await screen.findByRole("alert")).textContent).toBe("loop L1 owned twice");
    const [method, url, body] = put.mock.calls[0];
    expect([method, url]).toEqual(["PUT", "/api/site"]);
    expect((body as typeof SITE).tags).toHaveLength(2);
    put.mockResolvedValueOnce({});
    fireEvent.click(screen.getByText("Save equipment"));
    await waitFor(() => expect(screen.queryByRole("alert")).toBeNull());
  });

  it("offers only loops not owned elsewhere", async () => {
    render(<EquipmentEditor t={t} />);
    fireEvent.click(await screen.findByTestId("eq-a"));
    const select = screen.getByLabelText("Add to Owned loops") as HTMLSelectElement;
    expect(Array.from(select.options).map((o) => o.value)).toEqual(["", "L2"]);
  });
});
