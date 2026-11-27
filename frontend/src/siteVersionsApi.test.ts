// Tests for siteVersionsApi: URLs, bodies and the 202 (pending) versus 200 (published) split, api.ts mocked.
import { beforeEach, describe, expect, it, vi } from "vitest";

import * as api from "./api";
import {
  approvePublish,
  discardDraft,
  fetchDiff,
  fetchVersions,
  publishDraft,
  rejectPublish,
} from "./siteVersionsApi";

vi.mock("./api", async () => {
  const actual = await vi.importActual<typeof import("./api")>("./api");
  return { ...actual, getJson: vi.fn(), sendJson: vi.fn() };
});

beforeEach(() => vi.resetAllMocks());

describe("siteVersionsApi", () => {
  it("unwraps the version list", async () => {
    vi.mocked(api.getJson).mockResolvedValue({ versions: [{ version: 2 }] });
    expect(await fetchVersions()).toEqual([{ version: 2 }]);
    expect(api.getJson).toHaveBeenCalledWith("/api/site/versions");
  });

  it("asks for a diff between named documents", async () => {
    vi.mocked(api.getJson).mockResolvedValue({ sections: {}, empty: true });
    await fetchDiff(3, "draft");
    expect(api.getJson).toHaveBeenCalledWith("/api/site/diff?a=3&b=draft");
  });

  it("tells a published version from a pending request", async () => {
    vi.mocked(api.sendJson).mockResolvedValueOnce({ version: 2, sha256: "x" });
    expect(await publishDraft("n")).toEqual({ published: { version: 2, sha256: "x" } });
    expect(api.sendJson).toHaveBeenCalledWith("POST", "/api/site/publish", { note: "n" });
    vi.mocked(api.sendJson).mockResolvedValueOnce({ id: "p", reasons: ["loop:A"] });
    expect(await publishDraft("n")).toEqual({ pending: { id: "p", reasons: ["loop:A"] } });
  });

  it("approves, rejects and discards", async () => {
    vi.mocked(api.sendJson).mockResolvedValue({});
    await approvePublish();
    await rejectPublish("why");
    await discardDraft();
    expect(api.sendJson).toHaveBeenNthCalledWith(1, "POST", "/api/site/publish/approve", {});
    expect(api.sendJson).toHaveBeenNthCalledWith(2, "POST", "/api/site/publish/reject", { reason: "why" });
    expect(api.sendJson).toHaveBeenNthCalledWith(3, "DELETE", "/api/site/draft", {});
  });
});
