// src/components/SitePage.test.tsx
/**
 * Unit and component tests for the SitePage component (Phase 1, #36 exit criterion).
 * Verifies that SitePage correctly renders ConfigEditorPage for kind "site" and id "site",
 * handles document loading, and allows saving configuration changes.
 */

import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import * as api from "../api";
import { translate } from "../i18n";
import type { SchemaObject } from "../schemaFormModel";
import { SitePage } from "./SitePage";

const t = (key: string, params?: Record<string, string | number>) => translate("en", key, params);

const MOCK_SITE_SCHEMA: SchemaObject = {
  title: "Site configuration",
  type: "object",
  properties: {
    schema_version: {
      type: "integer",
      title: "Schema version",
    },
    site: {
      type: "object",
      title: "Site metadata",
    },
  },
};

const MOCK_SITE_DOC = {
  schema_version: 1,
  site: {
    name: "Test Plant",
    timezone: "UTC",
  },
};

describe("SitePage", () => {
  beforeEach(() => {
    vi.spyOn(api, "fetchSchema").mockResolvedValue(MOCK_SITE_SCHEMA);
    vi.spyOn(api, "fetchConfig").mockResolvedValue(MOCK_SITE_DOC);
    vi.spyOn(api, "saveConfig").mockResolvedValue(MOCK_SITE_DOC);
  });

  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it("requests the site schema and config with fixed kind 'site' and id 'site'", async () => {
    render(<SitePage t={t} />);

    await waitFor(() => {
      expect(api.fetchSchema).toHaveBeenCalledWith("site");
      expect(api.fetchConfig).toHaveBeenCalledWith("site", "site");
    });
  });

  it("renders the configuration editor title and fields", async () => {
    render(<SitePage t={t} />);

    await waitFor(() => {
      expect(screen.getByRole("heading", { name: "Configuration" })).toBeInTheDocument();
    });

    expect(screen.getByText("Schema version")).toBeInTheDocument();
    expect(screen.getByText("Site metadata")).toBeInTheDocument();
  });

  it("saves the site configuration when clicking the save button", async () => {
    render(<SitePage t={t} />);

    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Save" })).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => {
      expect(api.saveConfig).toHaveBeenCalledWith("site", "site", expect.objectContaining({
        schema_version: 1,
      }));
    });
  });
});
