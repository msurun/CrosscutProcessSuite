// frontend/src/tuningTestKit.tsx
// Test helpers of the tuning proposals view: proposal fixtures and a render that signs in a role.

import { render, screen } from "@testing-library/react";
import type { ReactElement } from "react";
import { vi } from "vitest";
import { AuthProvider, DEFAULT_ROLE_PERMISSIONS, useAuth } from "./AuthContext";
import * as authApi from "./authApi";
import type { TuningProposal } from "./tuningApi";

/** English-like translator: shows the key and the params, so tests can match both. */
export const mockT = (key: string, params?: Record<string, string | number>): string =>
  key + (params ? JSON.stringify(params) : "");

const FAR_FUTURE = "2099-01-01T00:00:00Z";

/** A queued proposal by "alice"; tests override what they are about. */
export function makeProposal(over: Partial<TuningProposal> = {}): TuningProposal {
  return {
    id: "p1",
    loop_id: "FIC101",
    created_by: "alice",
    created_at: "2026-11-05T10:00:00Z",
    expires_at: FAR_FUTURE,
    vendor_form: { key: "siemens_pid_compact", evidence: "verified" },
    source: {
      method: "simc",
      robustness: 0.5,
      window: { dataset_id: "mill", start: "2026-11-05T08:00:00Z", end: "2026-11-05T09:00:00Z" },
      step_test_id: "st-1",
    },
    confidence: { level: "high", reasons: ["verified form, sound fit, fresh window, step test"] },
    caveats: ["Ti is in seconds"],
    items: [
      { param: "gain", target: "FIC101.GAIN", unit: "-", from: 1, to: 1.5 },
      { param: "ti", target: "FIC101.TI", unit: "s", from: 30, to: 45 },
    ],
    preview: {
      label: "model prediction",
      iae_ratio: 0.8,
      overshoot_pct: { current: 12, proposed: 5 },
      settling_time_s: { current: 100, proposed: 70 },
      ms: { current: 1.8, proposed: 1.5 },
    },
    rollback_of: null,
    status: "queued",
    gateway_key: "k1",
    applied: null,
    review: null,
    rollback_recommended: false,
    ...over,
  };
}

/** Mocks the session of `role` ("off" = auth disabled) and renders `ui` once it is known. */
export async function renderAs(
  role: string,
  ui: ReactElement,
  username = role,
  readyId = "tuning-proposals-page",
) {
  if (role === "off") {
    vi.spyOn(authApi, "fetchMe").mockRejectedValue(new authApi.ApiError(401, "no session"));
    vi.spyOn(authApi, "fetchAuthConfig").mockResolvedValue({ auth_enabled: false, initialised: true });
  } else {
    vi.spyOn(authApi, "fetchMe").mockResolvedValue({
      user: { username, display_name: username },
      roles: [role],
      permissions: [...(DEFAULT_ROLE_PERMISSIONS[role] ?? [])],
      csrf: "tok",
      must_change_password: false,
    });
  }
  function Ready() {
    const { status } = useAuth();
    return status === "loading" ? null : ui;
  }
  const view = render(
    <AuthProvider>
      <Ready />
    </AuthProvider>,
  );
  await screen.findByTestId(readyId);
  return view;
}
