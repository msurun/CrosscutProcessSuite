// Tests for catalogueSourceApi: URLs, bodies and the presets unwrap, with api.ts mocked.
import { beforeEach, describe, expect, it, vi } from "vitest";

import * as api from "./api";
import { fetchNamingPresets, importCatalogue, previewCatalogue, testNamingRules } from "./catalogueSourceApi";

vi.mock("./api", async () => {
  const actual = await vi.importActual<typeof import("./api")>("./api");
  return { ...actual, getJson: vi.fn(), sendJson: vi.fn() };
});

beforeEach(() => vi.resetAllMocks());

describe("catalogueSourceApi", () => {
  it("unwraps the presets", async () => {
    vi.mocked(api.getJson).mockResolvedValue({ presets: { isa: [{ pattern: "x" }] } });
    expect(await fetchNamingPresets()).toEqual({ isa: [{ pattern: "x" }] });
    expect(api.getJson).toHaveBeenCalledWith("/api/catalogue/naming/presets");
  });

  it("posts the rule test", async () => {
    vi.mocked(api.sendJson).mockResolvedValue({});
    await testNamingRules([{ pattern: "p" }], ["A"]);
    expect(api.sendJson).toHaveBeenCalledWith("POST", "/api/catalogue/naming/test", {
      rules: [{ pattern: "p" }],
      tags: ["A"],
    });
  });

  it("previews with the root node by default and encodes the source id", async () => {
    vi.mocked(api.sendJson).mockResolvedValue({});
    await previewCatalogue("a b", []);
    expect(api.sendJson).toHaveBeenCalledWith("POST", "/api/sources/a%20b/catalogue-preview", {
      nodes: [null],
      rules: [],
    });
  });

  it("imports with the switches", async () => {
    vi.mocked(api.sendJson).mockResolvedValue({ added: { tags: 1, loops: 0, equipment: 0 } });
    await importCatalogue("s", [{ name: "A" }], [], { loops: true, equipment: false });
    expect(api.sendJson).toHaveBeenCalledWith("POST", "/api/sources/s/catalogue-import", {
      tags: [{ name: "A" }],
      rules: [],
      loops: true,
      equipment: false,
    });
  });
});
