// Playwright configuration for the browser smoke tests in `e2e/`. Expects the API on :8000 and the
// Vite dev server on :5173 to be running already (see README "End-to-end tests"). Uses the Chromium
// found in the Playwright cache (any revision) or the path in E2E_CHROMIUM.
import { defineConfig } from "@playwright/test";
import { existsSync, readdirSync } from "node:fs";
import { join } from "node:path";

const GATEWAY_LIVE = process.env.E2E_GATEWAY === "1";

/** Finds a Chromium executable: E2E_CHROMIUM, else the newest in the Playwright cache. */
function findChromium(): string | undefined {
  if (process.env.E2E_CHROMIUM) return process.env.E2E_CHROMIUM;
  const cache = join(process.env.LOCALAPPDATA ?? "", "ms-playwright");
  if (!existsSync(cache)) return undefined;
  const revisions = readdirSync(cache).filter((name) => /^chromium-\d+$/.test(name)).sort().reverse();
  const candidates = revisions.map((name) => join(cache, name, "chrome-win64", "chrome.exe"));
  return candidates.find((path) => existsSync(path));
}

export default defineConfig({
  testDir: "./e2e",
  timeout: 60_000,
  workers: 2,
  reporter: "list",
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://localhost:5173",
    locale: "pl-PL",
    launchOptions: { executablePath: findChromium() },
  },
  // Specs share one data root (site.json): runtime.spec.ts runs alone, after all the others.
  // gateway-live.spec.ts and tuning-live.spec.ts need the real gateway stack (E2E_GATEWAY=1, started
  // by run_e2e.mjs): with that switch they are the only projects, so no other spec runs against a
  // live gateway. tuning-live runs after gateway-live (which leaves the stack re-enabled and in
  // advisory mode) and sets up its own state.
  projects: GATEWAY_LIVE
    ? [
        { name: "gateway-live", testMatch: /gateway-live\.spec\.ts/ },
        { name: "tuning-live", testMatch: /tuning-live\.spec\.ts/, dependencies: ["gateway-live"] },
      ]
    : [
        { name: "main", testIgnore: /(runtime|gateway-live|tuning-live)\.spec\.ts/ },
        { name: "runtime", testMatch: /runtime\.spec\.ts/, dependencies: ["main"] },
      ],
});
