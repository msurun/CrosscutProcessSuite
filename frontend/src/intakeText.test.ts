// Tests of the translated Import wording: findings, notes and dry-run reasons by code, with the
// server's English as the fallback for unknown codes or missing figures.
import { describe, expect, it } from "vitest";
import type { IntakeFinding, IntakeNote } from "./api";
import { findingTexts, noteLines, noteText, reasonText } from "./intakeText";
import { translate } from "./i18n";

const pl = (key: string, params?: Record<string, string | number>) => translate("pl", key, params);
const es = (key: string, params?: Record<string, string | number>) => translate("es", key, params);

const LEAD: IntakeFinding = {
  code: "lead_too_short", text: "EN text", what_to_do: "EN todo", blocking: true,
  params: { share: 0.12, lead_s: 300, min_share: 0.2, need_s: 1200 },
};

describe("findingTexts", () => {
  it("translates by code and interpolates percentages and minutes", () => {
    const { text, todo } = findingTexts(LEAD, pl);
    expect(text).toContain("12 %");
    expect(text).toContain("5.0 min");
    expect(text).toContain("20 %");
    expect(todo).toContain("20.0 min");
    expect(text).not.toContain("EN text");
  });

  it("explains the post-move basis and the unknown dead time in Spanish", () => {
    const finding: IntakeFinding = {
      code: "post_move_too_short", text: "EN", what_to_do: "EN", blocking: true,
      params: { post_s: 60, need_s: 300, known: false, basis: "floor" },
    };
    const { text } = findingTexts(finding, es);
    expect(text).toContain("300 s");
    expect(text).toContain("desconocido");
  });

  it("adds the closed-loop sentence only for a blocking manual share", () => {
    const finding: IntakeFinding = { code: "not_in_manual", text: "EN", what_to_do: "EN", blocking: true, params: { share: 0.5, closed_loop: true } };
    expect(findingTexts(finding, pl).text).toContain("zamkniętej pętli");
    const soft = { ...finding, params: { share: 0.95, closed_loop: false } };
    expect(findingTexts(soft, pl).text).not.toContain("zamkniętej pętli");
  });

  it("translates the reasons inside a low-confidence finding", () => {
    const finding: IntakeFinding = { code: "low_confidence", text: "EN", what_to_do: "EN", blocking: false, params: { reasons: ["slope_se_over_20pct"] } };
    expect(findingTexts(finding, pl).text).toContain("Nachylenie jest niepewne");
  });

  it("falls back to the server text for an unknown code or missing figures", () => {
    const unknown: IntakeFinding = { code: "brand_new", text: "EN text", what_to_do: "EN todo", blocking: false };
    expect(findingTexts(unknown, pl)).toEqual({ text: "EN text", todo: "EN todo" });
    expect(findingTexts({ ...LEAD, params: {} }, pl)).toEqual({ text: "EN text", todo: "EN todo" });
  });
});

describe("notes and reasons", () => {
  const wide: IntakeNote = { code: "read_wide", text: "layout wide", params: { time: "iso", decimal: ",", delimiter: ";" } };

  it("translates read-as and assumption lines by code", () => {
    expect(noteText(wide, pl)).toContain("Układ: szeroki");
    expect(noteText(wide, pl)).toContain("Średnik");
    expect(noteText({ code: "resampling", text: "EN", params: { step_s: 2 } }, es)).toContain("2 s");
    expect(noteText({ code: "no_mode", text: "EN", params: {} }, pl)).toContain("MODE");
  });

  it("keeps the server text for an unknown note and the plain list for an old server", () => {
    expect(noteText({ code: "new_one", text: "EN note", params: {} }, pl)).toBe("EN note");
    expect(noteLines(undefined, ["plain"], pl)).toEqual(["plain"]);
  });

  it("reuses the tuning wizard's reason texts", () => {
    expect(reasonText("no_out_move", pl)).toBe(pl("tuning.ipdt.reason.no_out_move"));
    expect(reasonText("malformed_input", es)).toBe(es("import.reason.malformed_input"));
    expect(reasonText("something_else", pl)).toBe("something_else");
  });
});
