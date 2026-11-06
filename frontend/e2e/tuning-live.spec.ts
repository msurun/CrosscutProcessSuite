// Phase 3 exit criterion (docs/PRODUCT.md, TESTING_STRATEGY.md L5) on REAL processes:
// OPC UA server with simulated loop (PV, SP, OUT, MODE, KP, TI), gateway process (pinned policy with
// pid_param targets, plant map), API with authentication on, runtime service with loop_kpi and
// tuning_review jobs, and the browser.
//
// Shows proposal -> queued in confirm -> UI view -> self-approval refused -> viewer/operator refused ->
// lead approves in modal -> atomic write to OPC UA -> server parameters updated -> audit logged ->
// rollback proposal -> rollback approved -> parameters restored.
//
// Run: `E2E_GATEWAY=1 node e2e/support/run_e2e.mjs e2e/tuning-live.spec.ts` (the launcher starts the
// stack with start_gateway_stack.py and passes E2E_GW_*); skipped otherwise.
import { expect, test, type Browser, type BrowserContext, type Page } from "@playwright/test";

const ENV = process.env;
const CONTROL = ENV.E2E_GW_CONTROL_URL ?? "";
const USERS: Record<string, { role: string; password: string }> = JSON.parse(ENV.E2E_USERS ?? "{}");
const TUNING_INFO: {
  loop_id: string;
  gain_tag: string;
  ti_tag: string;
  dataset_id: string;
  initial_kp?: number;
  initial_ti?: number;
  review_window_s: number;
} = JSON.parse(ENV.E2E_GW_TUNING ?? "{}");
const LOOP = TUNING_INFO.loop_id ?? "TUNE1";
const GAIN_TAG = TUNING_INFO.gain_tag ?? "E2E.TUNE1.KP";
const TI_TAG = TUNING_INFO.ti_tag ?? "E2E.TUNE1.TI";
const DATASET = TUNING_INFO.dataset_id ?? "tuning_live_demo";
const URL_TUNING = `/#/d/${DATASET}/tuning`;
const STEP = { timeout: 30_000 };

test.describe.configure({ mode: "serial" });
test.skip(ENV.E2E_GATEWAY !== "1", "needs the real gateway stack (E2E_GATEWAY=1)");
test.setTimeout(180_000);

type Reply = { status: number; body: any };
type LiveNodes = {
  setpoint: number;
  mode: number;
  source: number;
  heartbeat: number;
  loop_pv: number;
  loop_sp: number;
  loop_out: number;
  loop_mode: number;
  kp: number;
  ti: number;
};

const pages = new Map<string, Page>();
const contexts: BrowserContext[] = [];

async function signedInPage(browser: Browser, name: string): Promise<Page> {
  const known = pages.get(name);
  if (known) return known;
  const context = await browser.newContext({ baseURL: ENV.E2E_BASE_URL, locale: "pl-PL" });
  contexts.push(context);
  const page = await context.newPage();
  await page.goto(URL_TUNING);
  await page.locator("#username").fill(name);
  await page.locator("#password").fill(USERS[name].password);
  await page.getByTestId("login-submit").click();
  await expect(page.getByTestId("role-badge-user")).toHaveAttribute("title", name, STEP);
  pages.set(name, page);
  return page;
}

/** One API call from inside the page (session cookie + CSRF header). */
async function api(page: Page, method: string, path: string, body?: unknown): Promise<Reply> {
  return page.evaluate(
    async ({ method, path, body }) => {
      const me = (await (await fetch("/api/auth/me", { credentials: "same-origin" })).json()) as { csrf: string };
      const headers: Record<string, string> = { "X-Crosscut-CSRF": me.csrf };
      if (body !== undefined) headers["Content-Type"] = "application/json";
      const reply = await fetch(`/api${path}`, {
        method,
        credentials: "same-origin",
        headers,
        body: body === undefined ? undefined : JSON.stringify(body),
      });
      const text = await reply.text();
      let parsed: unknown = text;
      try {
        parsed = text ? JSON.parse(text) : null;
      } catch {
        /* not JSON */
      }
      return { status: reply.status, body: parsed };
    },
    { method, path, body },
  );
}

async function nodes(): Promise<LiveNodes> {
  return (await (await fetch(`${CONTROL}/nodes`)).json()) as LiveNodes;
}

async function auditRecords(page: Page): Promise<{ records: Record<string, string>[]; chain_ok: boolean }> {
  return (await api(page, "GET", "/gateway/audit?limit=1000")).body;
}

test.afterAll(async () => {
  for (const context of contexts) await context.close();
});

let proposalId = "";
let proposedKp = 0;
let proposedTi = 0;

test("engineer sets up gateway state and creates tuning proposal: queued with SIMC parameters", async ({ browser }) => {
  const engineer = await signedInPage(browser, "e2e-engineer");

  // Re-enable parameter targets if they were stopped by prior kill tests
  const gwStatus = (await api(engineer, "GET", "/gateway/status")).body;
  for (const tag of [GAIN_TAG, TI_TAG]) {
    if (gwStatus.targets?.[tag] !== "enabled") {
      await api(engineer, "POST", `/gateway/targets/${tag}/re-enable`);
    }
  }

  // Gateway mode step-up: advisory -> dry_run -> confirm
  if (gwStatus.mode === "advisory") {
    await api(engineer, "PUT", "/gateway/mode", { mode: "dry_run" });
    await api(engineer, "PUT", "/gateway/mode", { mode: "confirm" });
  } else if (gwStatus.mode === "dry_run") {
    await api(engineer, "PUT", "/gateway/mode", { mode: "confirm" });
  }
  await expect.poll(async () => (await api(engineer, "GET", "/gateway/status")).body.mode, STEP).toBe("confirm");

  await engineer.goto(URL_TUNING);
  await expect(engineer.getByTestId("tuning-proposals-page")).toBeVisible(STEP);

  const body = {
    vendor_form: "siemens_pid_compact",
    method: "simc",
    reason: "live e2e test tuning proposal",
    dataset_id: DATASET,
    start_s: 0,
    end_s: 2400,
    robustness: 0.5,
  };
  const reply = await api(engineer, "POST", `/loops/${LOOP}/tuning/proposals`, body);
  expect(reply.status, JSON.stringify(reply.body)).toBe(201);
  const p = reply.body;
  proposalId = p.id;
  expect(p.status).toBe("queued");
  expect(p.gateway_key).toBeTruthy();
  expect(p.items.length).toBe(2);

  const gainItem = p.items.find((i: any) => i.param === "gain");
  const tiItem = p.items.find((i: any) => i.param === "ti");
  expect(gainItem).toBeDefined();
  expect(tiItem).toBeDefined();
  expect(gainItem.from).toBe(1.0);
  expect(tiItem.from).toBe(10.0);
  expect(gainItem.to).toBeGreaterThan(0.1);
  expect(tiItem.to).toBeGreaterThan(1.0);
  proposedKp = gainItem.to;
  proposedTi = tiItem.to;

  // View the proposal in the UI table
  await engineer.reload();
  await expect(engineer.getByTestId("tuning-proposals-page")).toBeVisible(STEP);
  const row = engineer.getByTestId(`tuning-row-${proposalId}`);
  await expect(row).toBeVisible(STEP);
  await row.getByRole("button").click();

  // Inspect detail panel
  await expect(engineer.getByTestId("tuning-detail")).toBeVisible(STEP);
  await expect(engineer.getByTestId("tuning-preview")).toBeVisible(STEP);
  await expect(engineer.getByTestId("tuning-confidence")).toBeVisible(STEP);

  // Self-approval is disabled for the creating engineer
  await expect(engineer.getByTestId("tuning-approve")).toHaveAttribute("aria-disabled", "true", STEP);
  const selfApprove = await api(engineer, "POST", `/tuning/proposals/${proposalId}/approve`);
  expect([403, 409], JSON.stringify(selfApprove.body)).toContain(selfApprove.status);
});

test("viewer and operator cannot approve the tuning proposal", async ({ browser }) => {
  const viewer = await signedInPage(browser, "e2e-viewer");
  await viewer.goto(URL_TUNING);
  await viewer.getByTestId(`tuning-row-${proposalId}`).getByRole("button").click();
  await expect(viewer.getByTestId("tuning-approve")).toHaveAttribute("aria-disabled", "true", STEP);
  await expect(viewer.getByTestId("tuning-rollback")).toHaveAttribute("aria-disabled", "true", STEP);
  const viewerApprove = await api(viewer, "POST", `/tuning/proposals/${proposalId}/approve`);
  expect(viewerApprove.status).toBe(403);

  const operator = await signedInPage(browser, "e2e-operator");
  await operator.goto(URL_TUNING);
  await operator.getByTestId(`tuning-row-${proposalId}`).getByRole("button").click();
  await expect(operator.getByTestId("tuning-approve")).toHaveAttribute("aria-disabled", "true", STEP);
  const operatorApprove = await api(operator, "POST", `/tuning/proposals/${proposalId}/approve`);
  expect(operatorApprove.status).toBe(403);
});

test("lead approves via modal: atomic write to OPC UA server, state becomes applied", async ({ browser }) => {
  const lead = await signedInPage(browser, "e2e-lead");
  await lead.goto(URL_TUNING);
  await lead.getByTestId(`tuning-row-${proposalId}`).getByRole("button").click();
  await expect(lead.getByTestId("tuning-detail")).toBeVisible(STEP);

  // Lead has gw.approve.tuning and is not the creator -> approve is enabled
  const approveBtn = lead.getByTestId("tuning-approve");
  await expect(approveBtn).not.toHaveAttribute("aria-disabled", "true", STEP);
  await approveBtn.click();

  // Approve dialog requires acknowledgment checkbox
  await expect(lead.getByTestId("tuning-approve-dialog")).toBeVisible(STEP);
  const confirmBtn = lead.getByTestId("tuning-approve-confirm");
  await expect(confirmBtn).toHaveAttribute("aria-disabled", "true", STEP);
  await lead.getByTestId("tuning-approve-check").check();
  await expect(confirmBtn).not.toHaveAttribute("aria-disabled", "true", STEP);
  await confirmBtn.click();

  // Status transitions to applied
  await expect.poll(async () => {
    const res = await api(lead, "GET", `/tuning/proposals/${proposalId}`);
    return res.body.status;
  }, STEP).toBe("applied");

  // Verify parameters were written to the real OPC UA server nodes
  await expect.poll(async () => (await nodes()).kp, STEP).toBeCloseTo(proposedKp, 2);
  await expect.poll(async () => (await nodes()).ti, STEP).toBeCloseTo(proposedTi, 2);

  // Verify audit log has param_write records with actor e2e-lead
  const audit = await auditRecords(lead);
  const writes = audit.records.filter((r) => r.event === "param_write");
  expect(writes.length).toBeGreaterThanOrEqual(2);
  expect(writes.map((r) => r.actor)).toContain("e2e-lead");
});

test("simulated process continues running with updated tuning parameters", async () => {
  const current = await nodes();
  expect(current.loop_pv).toBeGreaterThan(0);
  expect(current.loop_out).toBeGreaterThanOrEqual(0);
  expect(current.loop_out).toBeLessThanOrEqual(100);
  expect(Number.isFinite(current.loop_pv)).toBe(true);
});

test("rollback creates a reverse proposal and restoring initial parameters succeeds", async ({ browser }) => {
  const engineer = await signedInPage(browser, "e2e-engineer");
  await engineer.goto(URL_TUNING);
  await engineer.getByTestId(`tuning-row-${proposalId}`).getByRole("button").click();

  // Rollback button is enabled for an applied proposal
  const rollbackBtn = engineer.getByTestId("tuning-rollback");
  await expect(rollbackBtn).not.toHaveAttribute("aria-disabled", "true", STEP);
  await rollbackBtn.click();

  // Rollback modal dialog
  await expect(engineer.getByTestId("tuning-rollback-dialog")).toBeVisible(STEP);
  await engineer.getByTestId("tuning-rollback-reason").fill("reverting to initial tuning");
  await engineer.getByTestId("tuning-rollback-confirm").click();

  // Rollback proposal is created and queued
  let rollbackId = "";
  await expect.poll(async () => {
    const list = (await api(engineer, "GET", `/tuning/proposals?loop_id=${LOOP}`)).body;
    const rb = Array.isArray(list) ? list.find((p: any) => p.rollback_of === proposalId) : null;
    if (rb) rollbackId = rb.id;
    return rb?.status;
  }, STEP).toBe("queued");

  // Lead approves the rollback
  const lead = await signedInPage(browser, "e2e-lead");
  await lead.goto(URL_TUNING);
  await lead.getByTestId(`tuning-row-${rollbackId}`).getByRole("button").click();
  await lead.getByTestId("tuning-approve").click();
  await lead.getByTestId("tuning-approve-check").check();
  await lead.getByTestId("tuning-approve-confirm").click();

  await expect.poll(async () => {
    const res = await api(lead, "GET", `/tuning/proposals/${rollbackId}`);
    return res.body.status;
  }, STEP).toBe("applied");

  // The plant nodes on OPC UA return to initial values (1.0 and 10.0)
  await expect.poll(async () => (await nodes()).kp, STEP).toBeCloseTo(1.0, 2);
  await expect.poll(async () => (await nodes()).ti, STEP).toBeCloseTo(10.0, 2);
});
