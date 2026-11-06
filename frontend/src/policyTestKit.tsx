// frontend/src/policyTestKit.tsx
/**
 * Shared fixtures and render helpers for the policy panel tests: policy documents, API spies,
 * mocked sessions per role and a render that waits until the panel is on screen.
 */

import { render, screen } from "@testing-library/react";
import { vi } from "vitest";
import { AuthProvider, DEFAULT_ROLE_PERMISSIONS, useAuth } from "./AuthContext";
import * as authApi from "./authApi";
import { translate } from "./i18n";
import * as policyApi from "./policyApi";
import { PolicyError } from "./policyApi";
import { PolicyPanel } from "./PolicyPanel";
import type { PolicyDocument, TargetPolicy } from "./policyModel";

export const t = (key: string, params?: Record<string, string | number>) => translate("en", key, params);

export const TARGET: TargetPolicy = {
  limits: [0.0, 100.0],
  max_step: 2.0,
  max_rate_per_s: 1.0,
  min_interval_s: 1.0,
  allowed_loop_modes: ["CAS", "AUTO"],
  hold_off_s: 5.0,
  watchdog_s: 15.0,
  readback_tolerance: 0.1,
};

export const LIVE_DOC: PolicyDocument = {
  version: 1,
  mode: "advisory",
  targets: { "FIC101.SP": { ...TARGET } },
  custom_facility: "Plant-A",
};

export const LIVE: policyApi.LivePolicyResponse = {
  document: LIVE_DOC,
  pin: { digest: "file_digest_aaa", author: "engineer_author", approver: "lead_approver", approved_at: "2026-11-05T10:00:00Z" },
  mode_cap: "advisory",
  digest: "live_digest_111",
};

export const DRAFT_DOC: PolicyDocument = {
  version: 1,
  mode: "confirm",
  targets: { "FIC101.SP": { ...TARGET, max_step: 5.0 } },
};

export const DRAFT: policyApi.DraftPolicyResponse = {
  document: DRAFT_DOC,
  author: "engineer_author",
  saved_at: "2026-11-05T11:00:00Z",
  digest: "draft_digest_222",
};

/** Spies on the read endpoints; a null draft means 404 (no draft on the server). */
export function setupPolicySpies(live: policyApi.LivePolicyResponse = LIVE, draft: policyApi.DraftPolicyResponse | null = DRAFT) {
  const fetchLive = vi.spyOn(policyApi, "fetchLivePolicy").mockResolvedValue(live);
  const fetchDraft = vi.spyOn(policyApi, "fetchDraftPolicy");
  if (draft) fetchDraft.mockResolvedValue(draft);
  else fetchDraft.mockRejectedValue(new PolicyError(404, "no draft"));
  return { fetchLive, fetchDraft };
}

/** Mocks the session: role "off" means authentication disabled (the actor is local-dev). */
export function mockAuthSession(role: string, username: string) {
  if (role === "off") {
    vi.spyOn(authApi, "fetchAuthConfig").mockResolvedValue({ auth_enabled: false, initialised: true });
    vi.spyOn(authApi, "fetchMe").mockRejectedValue(new authApi.ApiError(401, "no session"));
    return;
  }
  vi.spyOn(authApi, "fetchAuthConfig").mockResolvedValue({ auth_enabled: true, initialised: true });
  vi.spyOn(authApi, "fetchMe").mockResolvedValue({
    user: { username, display_name: username },
    roles: [role],
    permissions: [...(DEFAULT_ROLE_PERMISSIONS[role] ?? [])],
    csrf: "tok",
    must_change_password: false,
  });
}

function Ready({ gatewayMode, translateFn }: { gatewayMode?: string; translateFn: typeof t }) {
  const { status } = useAuth();
  return status === "loading" ? null : <PolicyPanel gatewayMode={gatewayMode} t={translateFn} />;
}

export interface RenderOptions {
  username?: string;
  /** Gateway mode; the string "unknown" renders the panel without the prop. */
  gatewayMode?: string;
  translateFn?: typeof t;
}

/** Renders the panel for `role` and waits until it has loaded. */
export async function renderPanel(role: string, options: RenderOptions = {}) {
  mockAuthSession(role, options.username ?? role);
  const mode = options.gatewayMode === "unknown" ? undefined : (options.gatewayMode ?? "advisory");
  const view = render(
    <AuthProvider t={t}>
      <Ready gatewayMode={mode} translateFn={options.translateFn ?? t} />
    </AuthProvider>,
  );
  await screen.findByTestId("policy-panel");
  return view;
}

export function isDisabled(el: HTMLElement): boolean {
  return el.getAttribute("aria-disabled") === "true";
}

export function reasonOf(el: HTMLElement): string {
  return el.getAttribute("title") ?? "";
}
