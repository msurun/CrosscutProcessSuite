// Playwright end-to-end tests for roles and authentication (issue #47, ADR 013).
// Runs only against an API started with authentication ON: `E2E_AUTH=1 node e2e/support/run_e2e.mjs
// e2e/auth.spec.ts` (the launcher creates the first admin). Skipped in the default run, where auth is off.
// The Write Gateway process is not running here, so the gateway page shows its not-running state:
// mode options and the kill button are still rendered and are what these tests check.
import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

const DATASET = "mill_circuit_observational_seed42";
const URL_GATEWAY = `/#/d/${DATASET}/gateway`;
const URL_USERS = `/#/d/${DATASET}/users`;
const ADMIN_USER = process.env.E2E_ADMIN_USER ?? "e2e-admin";
const ADMIN_PASSWORD = process.env.E2E_ADMIN_PASSWORD ?? "";
const OPERATOR = { name: "e2e-operator", role: "operator", password: "operator-pass-1234" };
const VIEWER = { name: "e2e-viewer", role: "viewer", password: "viewer-pass-123456" };
const USERS_TAB = /^(Users|Użytkownicy|Usuarios)$/;

test.describe.configure({ mode: "serial" });
test.skip(process.env.E2E_AUTH !== "1", "needs the API with authentication on (E2E_AUTH=1)");

async function signIn(page: Page, username: string, password: string, url = URL_GATEWAY): Promise<void> {
  await page.goto(url);
  await page.locator("#username").fill(username);
  await page.locator("#password").fill(password);
  await page.getByTestId("login-submit").click();
}

async function expectSignedIn(page: Page, username: string): Promise<void> {
  await expect(page.getByTestId("role-badge-user")).toHaveAttribute("title", username, { timeout: 30_000 });
}

async function createUser(page: Page, user: typeof OPERATOR): Promise<void> {
  await page.getByTestId("open-create-user").click();
  const dialog = page.getByTestId("create-user-dialog");
  await dialog.locator("#create-username").fill(user.name);
  await dialog.locator("#create-display-name").fill(user.name);
  await dialog.locator("#create-password").fill(user.password);
  await dialog.getByTestId("role-checkbox-viewer").uncheck();
  await dialog.getByTestId(`role-checkbox-${user.role}`).check();
  await dialog.locator("input[type=checkbox]:not([data-testid])").uncheck();
  await dialog.getByTestId("create-user-submit").click();
}

async function confirmStepUp(page: Page): Promise<void> {
  await expect(page.getByTestId("stepup-dialog")).toBeVisible({ timeout: 30_000 });
  await page.locator("#stepup-password").fill(ADMIN_PASSWORD);
  await page.getByTestId("stepup-submit").click();
  await expect(page.getByTestId("stepup-dialog")).toBeHidden({ timeout: 30_000 });
}

async function signOut(page: Page): Promise<void> {
  await page.getByTestId("role-badge-logout").click();
  await expect(page.locator("#username")).toBeVisible({ timeout: 30_000 });
}

test("wrong password shows an error and stays on the login", async ({ page }) => {
  await signIn(page, ADMIN_USER, "not-the-password-0");
  await expect(page.getByTestId("login-error-summary")).toBeVisible({ timeout: 30_000 });
  await expect(page.getByTestId("role-badge-user")).toHaveCount(0);
});

test("admin signs in, sees the role badge and the Users tab", async ({ page }) => {
  await signIn(page, ADMIN_USER, ADMIN_PASSWORD);
  await expectSignedIn(page, ADMIN_USER);
  await expect(page.getByTestId("role-badge-chips")).toBeVisible();
  await expect(page.locator("nav.view-tabs button").filter({ hasText: USERS_TAB })).toBeVisible();
});

test("admin creates an operator and a viewer (step-up dialog), then logs out", async ({ page }) => {
  await signIn(page, ADMIN_USER, ADMIN_PASSWORD, URL_USERS);
  await expectSignedIn(page, ADMIN_USER);
  await createUser(page, OPERATOR);
  await confirmStepUp(page);
  await expect(page.getByTestId(`user-row-${OPERATOR.name}`)).toBeVisible({ timeout: 30_000 });
  await createUser(page, VIEWER);
  await expect(page.getByTestId(`user-row-${VIEWER.name}`)).toBeVisible({ timeout: 30_000 });
  await signOut(page);
});

test("operator: no Users tab, mode-up options disabled with a reason, kill enabled", async ({ page }) => {
  await signIn(page, OPERATOR.name, OPERATOR.password);
  await expectSignedIn(page, OPERATOR.name);
  await expect(page.getByTestId("gateway-mode-select")).toBeVisible({ timeout: 30_000 });
  await expect(page.locator("nav.view-tabs button").filter({ hasText: USERS_TAB })).toHaveCount(0);
  for (const mode of ["advisory", "dry_run", "confirm", "supervised"]) {
    const option = page.getByTestId(`gateway-mode-option-${mode}`);
    await expect(option).toHaveJSProperty("disabled", true);
    expect(await option.getAttribute("title")).toBeTruthy();
  }
  await expect(page.getByTestId("gateway-kill-button")).toBeEnabled();
  await expect(page.getByTestId("gateway-kill-button")).not.toHaveAttribute("aria-disabled", "true");
  await page.goto(URL_USERS);
  await expect(page.getByRole("alert").filter({ hasText: /\S/ }).first()).toBeVisible();
  await expect(page.getByTestId("open-create-user")).toHaveCount(0);
});

test("viewer: the API refuses an approval", async ({ page }) => {
  await signIn(page, VIEWER.name, VIEWER.password);
  await expectSignedIn(page, VIEWER.name);
  const status = await page.evaluate(async () => {
    const me = (await (await fetch("/api/auth/me", { credentials: "same-origin" })).json()) as { csrf: string };
    const reply = await fetch("/api/gateway/pending/none/approve", {
      method: "POST",
      credentials: "same-origin",
      headers: { "X-Crosscut-CSRF": me.csrf },
    });
    return reply.status;
  });
  expect(status).toBe(403);
});

test("an ended session returns to the login", async ({ page }) => {
  await signIn(page, OPERATOR.name, OPERATOR.password);
  await expectSignedIn(page, OPERATOR.name);
  await expect(page.getByTestId("gateway-mode-select")).toBeVisible({ timeout: 30_000 });
  await page.context().clearCookies();
  await expect(page.locator("#username")).toBeVisible({ timeout: 30_000 });
  await expect(page.getByTestId("role-badge-user")).toHaveCount(0);
});

for (const width of [1440, 390] as const) {
  test(`login and users pages have no axe violations @${width}`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await page.goto(URL_GATEWAY);
    await expect(page.locator("#username")).toBeVisible({ timeout: 30_000 });
    await expectNoViolations(page, width);
    await signIn(page, ADMIN_USER, ADMIN_PASSWORD, URL_USERS);
    await expect(page.getByTestId(`user-row-${OPERATOR.name}`)).toBeVisible({ timeout: 30_000 });
    await expectNoViolations(page, width);
  });
}

async function expectNoViolations(page: Page, width: number): Promise<void> {
  if (width === 390) {
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    expect(overflow, "horizontal page scroll").toBeLessThanOrEqual(0);
  }
  const axe = await new AxeBuilder({ page }).analyze();
  const bad = axe.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
  const lines = bad.map((v) => `${v.id}: ${v.nodes.slice(0, 3).map((n) => n.target.join(" ")).join(" | ")}`);
  expect(lines).toEqual([]);
}
