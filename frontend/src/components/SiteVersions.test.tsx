// Tests for SiteVersions (#165): draft badge, publish with a note, the pending approval entry and its
// approve/reject buttons. The client is mocked; t returns the key.
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import * as api from "../siteVersionsApi";
import { SiteVersions } from "./SiteVersions";

vi.mock("../siteVersionsApi");

const t = (key: string, vars?: Record<string, string | number>) => (vars ? `${key} ${JSON.stringify(vars)}` : key);
const diff: api.SiteDiff = {
  sections: { loops: { added: [], removed: [], changed: [{ id: "L1", fields: [{ field: "type", before: "a", after: "b" }] }] } },
  empty: false,
};
const base: api.SiteStatus = {
  published_version: 1,
  has_published: true,
  published_matches_version: true,
  has_draft: true,
  draft_changed: true,
  draft_sections: ["loops"],
  pending: null,
};

beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(api.fetchSiteStatus).mockResolvedValue(base);
  vi.mocked(api.fetchVersions).mockResolvedValue([
    { version: 1, sha256: "x", author: "eng1", approver: null, time: "2026-11-26T10:00:00+00:00", note: "base" },
  ]);
  vi.mocked(api.fetchDiff).mockResolvedValue(diff);
});

describe("SiteVersions", () => {
  it("shows the draft badge and the diff, and publishes with the note", async () => {
    vi.mocked(api.publishDraft).mockResolvedValue({ published: { version: 2 } as api.VersionMeta });
    render(<SiteVersions t={t} />);
    expect((await screen.findByTestId("draft-badge")).textContent).toBe("versions.draft");
    expect(screen.getByText("L1")).toBeTruthy();
    fireEvent.change(screen.getByLabelText("versions.note"), { target: { value: "why" } });
    fireEvent.click(screen.getByRole("button", { name: "versions.publish" }));
    await waitFor(() => expect(api.publishDraft).toHaveBeenCalledWith("why"));
    await screen.findByText('versions.published {"n":2}');
  });

  it("says approval is needed when the server answers with a pending request", async () => {
    vi.mocked(api.publishDraft).mockResolvedValue({ pending: {} as api.PendingPublish });
    render(<SiteVersions t={t} />);
    fireEvent.click(await screen.findByRole("button", { name: "versions.publish" }));
    await screen.findByText("versions.requested");
  });

  it("offers approve and reject for a pending request", async () => {
    const pending: api.PendingPublish = {
      id: "p1", requested_by: "eng1", requested_at: "t", note: "n", reasons: ["loop:L1"], diff,
    };
    vi.mocked(api.fetchSiteStatus).mockResolvedValue({ ...base, pending });
    vi.mocked(api.approvePublish).mockResolvedValue({ version: 2 } as api.VersionMeta);
    render(<SiteVersions t={t} />);
    const entry = await screen.findByTestId("pending-publish");
    expect(entry.textContent).toContain("loop:L1");
    expect(screen.queryByRole("button", { name: "versions.publish" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "versions.approve" }));
    await waitFor(() => expect(api.approvePublish).toHaveBeenCalled());
  });

  it("shows the changes of a stored version", async () => {
    vi.mocked(api.fetchSiteStatus).mockResolvedValue({ ...base, has_draft: false, draft_changed: false });
    render(<SiteVersions t={t} />);
    fireEvent.click(await screen.findByRole("button", { name: 'versions.showChanges {"n":1}' }));
    await waitFor(() => expect(api.fetchDiff).toHaveBeenCalledWith("published", 1));
    await screen.findByText('versions.changesOf {"n":1}', { selector: "h4" });
  });
});
