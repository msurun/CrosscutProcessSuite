// Phase 2 exit criterion (docs/PRODUCT.md, TESTING_STRATEGY.md L5) on REAL processes: an OPC UA server
// with writable nodes, the gateway process (key file, pinned policy, plant map), the API with
// authentication on and the browser. Shows proposal -> confirm -> write -> read-back -> audit, the
// kill, the operator takeover hold-off and roles without permission being refused.
// Run: `E2E_GATEWAY=1 node e2e/support/run_e2e.mjs e2e/gateway-live.spec.ts` (the launcher starts the
// stack with start_gateway_stack.py and passes E2E_GW_*); skipped otherwise.
import { expect, test, type Browser, type BrowserContext, type Page } from "@playwright/test";
import { spawnSync } from "node:child_process";
import { existsSync } from "node:fs";
import { join } from "node:path";

const DATASET = "mill_circuit_observational_seed42";
const URL_GATEWAY = `/#/d/${DATASET}/gateway`;
const ENV = process.env;
const TAG = ENV.E2E_GW_TAG ?? "";
const CONTROL = ENV.E2E_GW_CONTROL_URL ?? "";
const ROOT = ENV.E2E_GW_ROOT ?? "";
const HOLD_OFF_S = Number(ENV.E2E_GW_HOLD_OFF_S ?? "8");
const USERS: Record<string, { role: string; password: string }> = JSON.parse(ENV.E2E_USERS ?? "{}");
const STEP = { timeout: 30_000 };

test.describe.configure({ mode: "serial" });
test.skip(ENV.E2E_GATEWAY !== "1", "needs the real gateway stack (E2E_GATEWAY=1)");
test.setTimeout(180_000);

type Reply = { status: number; body: any };
type Nodes = { setpoint: number; mode: number; source: number; heartbeat: number };

const pages = new Map<string, Page>();
const contexts: BrowserContext[] = [];

async function signedInPage(browser: Browser, name: string): Promise<Page> {
  const known = pages.get(name);
  if (known) return known;
  const context = await browser.newContext({ baseURL: ENV.E2E_BASE_URL, locale: "pl-PL" });
  contexts.push(context);
  const page = await context.newPage();
  await page.goto(URL_GATEWAY);
  await page.locator("#username").fill(name);
  await page.locator("#password").fill(USERS[name].password);
  await page.getByTestId("login-submit").click();
  await expect(page.getByTestId("role-badge-user")).toHaveAttribute("title", name, STEP);
  await expect(page.getByTestId("gateway-mode-select")).toBeVisible(STEP);
  pages.set(name, page);
  return page;
}

/** One API call from inside the page (session cookie + CSRF header), like the app does. */
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
        /* not JSON (for example a plain-text 500): keep the text */
      }
      return { status: reply.status, body: parsed };
    },
    { method, path, body },
  );
}

async function nodes(): Promise<Nodes> {
  return (await (await fetch(`${CONTROL}/nodes`)).json()) as Nodes;
}

async function targetState(page: Page): Promise<string> {
  return (await api(page, "GET", "/gateway/status")).body.targets[TAG];
}

async function auditRecords(page: Page): Promise<{ records: Record<string, string>[]; chain_ok: boolean }> {
  return (await api(page, "GET", "/gateway/audit?limit=1000")).body;
}

/** Signs a `propose` envelope with the gateway key (python helper) and returns its outcome. */
function propose(value: number, actor = "svc:runtime", roles = "service"): any {
  const args = [ENV.E2E_GW_PROPOSE_SCRIPT ?? "", "--root", ROOT, "--tag", TAG, "--value", String(value), "--actor", actor, "--roles", roles];
  const run = spawnSync(ENV.E2E_PYTHON ?? "python", args, { encoding: "utf-8" });
  if (run.status !== 0) throw new Error(`propose helper failed: ${run.stderr}`);
  return JSON.parse(run.stdout.trim().split("\n").pop() ?? "{}");
}

async function pendingKey(page: Page, proposer: string): Promise<string> {
  let key = "";
  await expect
    .poll(async () => {
      const list = (await api(page, "GET", "/gateway/pending")).body as { key: string; proposer: string }[];
      key = list.find((item) => item.proposer === proposer)?.key ?? "";
      return key;
    }, STEP)
    .not.toBe("");
  return key;
}

async function approveByApi(page: Page, key: string): Promise<void> {
  const reply = await api(page, "POST", `/gateway/pending/${key}/approve`);
  expect(reply.status, JSON.stringify(reply.body)).toBe(200);
}

test.afterAll(async () => {
  for (const context of contexts) await context.close();
});

test("engineer raises the mode advisory -> dry_run -> confirm; supervised stays disabled", async ({ browser }) => {
  const page = await signedInPage(browser, "e2e-engineer");
  await expect(page.getByTestId("gateway-mode-chip")).toHaveText("advisory", STEP);
  await page.getByTestId("gateway-mode-select").selectOption("dry_run");
  await expect(page.getByTestId("gateway-mode-chip")).toHaveText("dry_run", STEP);
  await page.getByTestId("gateway-mode-select").selectOption("confirm");
  await expect(page.getByTestId("gateway-mode-chip")).toHaveText("confirm", STEP);
  const supervised = page.getByTestId("gateway-mode-option-supervised");
  await expect(supervised).toHaveJSProperty("disabled", true);
  expect(await supervised.getAttribute("title")).toBeTruthy();
  await expect(page.getByTestId("gateway-error")).toHaveCount(0);
});

test("proposal -> operator approves -> clamped value on the server, read-back keeps it enabled", async ({ browser }) => {
  const outcome = propose(80);
  expect(outcome.decision).toMatchObject({ accepted: true, reason_code: "queued", clamped_value: 55 });
  const operator = await signedInPage(browser, "e2e-operator");
  const key = await pendingKey(operator, "svc:runtime");
  await expect(operator.getByTestId(`gateway-pending-${key}`)).toBeVisible(STEP);
  await operator.getByTestId(`gateway-approve-${key}`).click();
  await expect.poll(async () => (await nodes()).setpoint, STEP).toBe(55);
  expect((await nodes()).source).toBe(1);
  await expect.poll(async () => (await nodes()).heartbeat, STEP).toBeGreaterThanOrEqual(3);
  expect(await targetState(operator)).toBe("enabled");
  await expect(operator.getByTestId(`gateway-target-${TAG}`)).toContainText("enabled", STEP);
});

test("the audit shows proposal, queued and write with their actors", async ({ browser }) => {
  const records = (await auditRecords(await signedInPage(browser, "e2e-lead"))).records;
  const of = (event: string) => records.find((r) => r.event === event && r.tag === TAG);
  expect(of("proposal")?.actor).toBe("svc:runtime");
  expect(of("queued")).toMatchObject({ actor: "svc:runtime", value: "55.0" });
  expect(of("write")).toMatchObject({ actor: "e2e-operator", value: "55.0", reason_code: "clamped" });
});

test("proposer == approver is refused; a viewer cannot approve", async ({ browser }) => {
  expect(propose(58, "e2e-engineer", "engineer").decision).toMatchObject({ accepted: true });
  const engineer = await signedInPage(browser, "e2e-engineer");
  const key = await pendingKey(engineer, "e2e-engineer");
  // Refused: 403 once the gateway answers refusals, 504 while it files them without an answer.
  const self = await api(engineer, "POST", `/gateway/pending/${key}/approve`);
  expect([403, 409, 504], JSON.stringify(self.body)).toContain(self.status);
  await expect(engineer.getByTestId(`gateway-pending-${key}`)).toBeVisible(STEP);
  expect((await nodes()).setpoint).toBe(55);
  // The gateway files the refusal asynchronously: poll the audit instead of reading it once.
  const lastRefusal = async () => (await auditRecords(engineer)).records.filter((r) => r.event === "auth_reject").at(-1);
  await expect.poll(lastRefusal, STEP).toMatchObject({ actor: "e2e-engineer", reason_code: "self_approval", value: "approve" });
  const viewer = await signedInPage(browser, "e2e-viewer");
  await expect(viewer.getByTestId(`gateway-approve-${key}`)).toHaveAttribute("aria-disabled", "true", STEP);
  expect((await api(viewer, "POST", `/gateway/pending/${key}/approve`)).status).toBe(403);
  const operator = await signedInPage(browser, "e2e-operator");
  await approveByApi(operator, key);
  await expect.poll(async () => (await nodes()).setpoint, STEP).toBe(58);
});

test("operator takeover: hold_off within a few ticks, proposals refused, re-enable rules", async ({ browser }) => {
  const operator = await signedInPage(browser, "e2e-operator");
  const viewer = await signedInPage(browser, "e2e-viewer");
  const takeover = await fetch(`${CONTROL}/takeover`, { method: "POST" });
  expect(takeover.status).toBe(200);
  await expect.poll(() => targetState(operator), { timeout: 15_000 }).toBe("hold_off");
  const reEnable = `/gateway/targets/${TAG}/re-enable`;
  const early = await api(operator, "POST", reEnable);
  expect(early.status, JSON.stringify(early.body)).toBe(409);
  expect((await api(viewer, "POST", reEnable)).status).toBe(403);
  await expect(operator.getByTestId(`gateway-reenable-${TAG}`)).not.toHaveAttribute("aria-disabled", "true", STEP);
  await expect(viewer.getByTestId(`gateway-reenable-${TAG}`)).toHaveAttribute("aria-disabled", "true", STEP);
  expect(propose(57).decision).toMatchObject({ accepted: false, reason_code: "target_hold_off" });
  await expect.poll(async () => (await api(operator, "POST", reEnable)).status, { timeout: HOLD_OFF_S * 1000 + 20_000 }).toBe(200);
  expect(await targetState(operator)).toBe("enabled");
  const events = (await auditRecords(operator)).records.map((r) => r.event);
  expect(events).toContain("operator_override");
});

test("kill by a viewer stops every target within one cycle and refuses proposals", async ({ browser }) => {
  const operator = await signedInPage(browser, "e2e-operator");
  expect(propose(56).decision).toMatchObject({ accepted: true, reason_code: "queued" });
  await approveByApi(operator, await pendingKey(operator, "svc:runtime"));
  await expect.poll(async () => (await nodes()).setpoint, STEP).toBe(56);
  await expect.poll(async () => (await nodes()).source, STEP).toBe(1);
  const viewer = await signedInPage(browser, "e2e-viewer");
  await viewer.getByTestId("gateway-kill-button").click();
  await viewer.getByTestId("kill-confirm-ok").click();
  await expect.poll(() => targetState(operator), { timeout: 4000, intervals: [200] }).toBe("killed");
  await expect.poll(async () => (await nodes()).source, { timeout: 5000, intervals: [200] }).toBe(0);
  expect(existsSync(join(ROOT, "_gateway", "KILLED"))).toBe(true);
  expect(propose(55).decision).toMatchObject({ accepted: false, reason_code: "killed" });
  const killEvent = (await auditRecords(viewer)).records.find((r) => r.event === "kill");
  expect(killEvent?.actor).toBe("e2e-viewer");
});

test("kill_reset by the lead needs step-up, then re-enable only per target by an engineer", async ({ browser }) => {
  const lead = await signedInPage(browser, "e2e-lead");
  const operator = await signedInPage(browser, "e2e-operator");
  expect((await api(operator, "POST", "/gateway/kill/reset")).status).toBe(403);
  expect((await api(lead, "POST", "/gateway/kill/reset")).status).toBe(428);
  const stepUp = await api(lead, "POST", "/auth/stepup", { password: USERS["e2e-lead"].password });
  expect(stepUp.status).toBe(200);
  expect((await api(lead, "POST", "/gateway/kill/reset")).status).toBe(200);
  await expect.poll(() => targetState(lead), STEP).toBe("stopped:kill");
  expect((await api(lead, "GET", "/gateway/status")).body.mode).toBe("advisory");
  expect(existsSync(join(ROOT, "_gateway", "KILLED"))).toBe(false);
  const reEnable = `/gateway/targets/${TAG}/re-enable`;
  expect((await api(operator, "POST", reEnable)).status).toBe(403);
  const engineer = await signedInPage(browser, "e2e-engineer");
  await engineer.getByTestId(`gateway-reenable-${TAG}`).click();
  await expect.poll(() => targetState(engineer), STEP).toBe("enabled");
});

test("the audit chain is intact at the end and shows who did what", async ({ browser }) => {
  const engineer = await signedInPage(browser, "e2e-engineer");
  await expect(engineer.getByTestId("gateway-chain-status")).toHaveClass(/status-chip--ok/, STEP);
  const audit = await auditRecords(engineer);
  expect(audit.chain_ok).toBe(true);
  const actors = (event: string) => audit.records.filter((r) => r.event === event).map((r) => r.actor);
  expect(actors("kill_reset")).toEqual(["e2e-lead"]);
  expect(actors("re_enable")).toContain("e2e-engineer");
  expect(actors("mode_change")).toContain("e2e-engineer");
});
