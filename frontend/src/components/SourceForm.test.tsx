// Tests for SourceForm: driver-dependent fields, write-only secret, test-draft and 422 problems.
// The client is mocked; t returns the key so assertions do not depend on a language.
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "../api";
import * as api from "../sourceAdminApi";
import { SourceForm } from "./SourceForm";

vi.mock("../sourceAdminApi", () => ({
  fetchSecretStored: vi.fn(),
  putSecret: vi.fn(),
  saveSource: vi.fn(),
  testDraft: vi.fn(),
}));

const t = (key: string, vars?: Record<string, string | number>) => (vars ? `${key} ${JSON.stringify(vars)}` : key);

beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(api.fetchSecretStored).mockResolvedValue(false);
  vi.mocked(api.saveSource).mockImplementation(async (e) => ({ ...e, secret_stored: false }));
});

function pick(label: string, value: string) {
  fireEvent.change(screen.getByLabelText(label), { target: { value } });
}

describe("SourceForm", () => {
  it("shows fields by driver", () => {
    render(<SourceForm t={t} onSaved={vi.fn()} onCancel={vi.fn()} />);
    expect(screen.getByLabelText("sources.endpoint")).toBeTruthy();
    pick("sources.driver", "piwebapi");
    expect(screen.getByLabelText("sources.baseUrl")).toBeTruthy();
    expect(screen.queryByLabelText("sources.endpoint")).toBeNull();
    pick("sources.driver", "sql");
    expect(screen.getByLabelText("sources.profile")).toBeTruthy();
  });

  it("saves first, then sends the secret only to the secret route and clears the field", async () => {
    const onSaved = vi.fn();
    render(<SourceForm t={t} onSaved={onSaved} onCancel={vi.fn()} />);
    pick("sources.id", "hist");
    pick("sources.driver", "sql");
    pick("sources.authKind", "basic");
    const field = screen.getByLabelText("sources.password") as HTMLInputElement;
    expect(field.type).toBe("password");
    expect(field.autocomplete).toBe("off");
    fireEvent.change(field, { target: { value: "s3cret" } });
    fireEvent.click(screen.getByRole("button", { name: "sources.save" }));
    await waitFor(() => expect(api.putSecret).toHaveBeenCalledWith("hist", "s3cret"));
    const saved = vi.mocked(api.saveSource).mock.calls[0][0];
    expect(JSON.stringify(saved)).not.toContain("s3cret");
    expect(saved.auth).toEqual({ kind: "basic", credential_ref: "source.hist" });
    expect((screen.getByLabelText("sources.password") as HTMLInputElement).value).toBe("");
    expect(onSaved).toHaveBeenCalled();
  });

  it("tests the draft and shows the capabilities", async () => {
    vi.mocked(api.testDraft).mockResolvedValue({ status: "ok", capabilities: ["history", "browse"] });
    render(<SourceForm t={t} onSaved={vi.fn()} onCancel={vi.fn()} />);
    pick("sources.id", "d");
    fireEvent.click(screen.getByRole("button", { name: "sources.test" }));
    expect((await screen.findByRole("status")).textContent).toContain("history, browse");
  });

  it("shows the 422 problems and does not call onSaved", async () => {
    vi.mocked(api.saveSource).mockRejectedValue(new ApiError(422, "bad endpoint\nbad id"));
    const onSaved = vi.fn();
    render(<SourceForm t={t} onSaved={onSaved} onCancel={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "sources.save" }));
    expect((await screen.findByRole("alert")).textContent).toContain("bad endpoint");
    expect(onSaved).not.toHaveBeenCalled();
  });

  it("shows whether a secret is stored, never its value", async () => {
    vi.mocked(api.fetchSecretStored).mockResolvedValue(true);
    render(
      <SourceForm
        t={t}
        initial={{ id: "pi", driver: "piwebapi", auth: { kind: "bearer", credential_ref: "source.pi" } }}
        onSaved={vi.fn()}
        onCancel={vi.fn()}
      />,
    );
    expect(await screen.findByText("sources.secretStored")).toBeTruthy();
    expect((screen.getByLabelText("sources.token") as HTMLInputElement).value).toBe("");
  });
});
