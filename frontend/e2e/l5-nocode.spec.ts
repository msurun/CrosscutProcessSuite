// L5 no-code acceptance (#151, Phase 1 and 3 exit criterion): from an EMPTY project to a live KPI, a
// tuning write in confirm mode and its rollback, against live RougherSim, entirely through the browser.
//
// Nothing is configured by file: the data root starts with no site.json and no jobs.json, and every
// step below is a click or a typed value in the GUI (the spec only reads the plant through the rig's
// read-only control channel and the audit through the API). The rig (start_l5_stack.py) provides what
// a plant already has: the OPC UA server, a history extract of the loop and the gateway with the
// plant owner's signed policy.
//
// Steps: engineer adds the OPC UA source and tests the connection -> builds the catalogue from the
// source browse (preset roles, loops) -> creates the loop_kpi job -> sees the live KPI -> lead raises
// the gateway to confirm -> engineer proposes a tuning change from the Tuning view -> it waits in the
// gateway queue -> lead approves -> the server has the new parameters and the KPI row keeps updating
// -> engineer rolls back, lead approves -> the previous parameters are on the server again.
//
// Run: `E2E_L5_NOCODE=1 ROUGHERSIM_DIR=<pinned checkout> node e2e/support/run_e2e.mjs
// e2e/l5-nocode.spec.ts` (nightly L5 only, see docs/L5_FINDINGS.md); skipped without E2E_L5_NOCODE.
import { expect, test, type Browser, type BrowserContext, type Page } from "@playwright/test";
import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

const ENV = process.env;
const INFO: {
  root: string;
  opcua_endpoint: string;
  control_url: string;
  loop: string;
  gain_tag: string;
  ti_tag: string;
  dataset: string;
  initial_gain: number;
  initial_ti: number;
} = JSON.parse(ENV.E2E_L5_INFO ?? "{}");
const USERS: Record<string, { role: string; password: string }> = JSON.parse(ENV.E2E_USERS ?? "{}");
const SOURCE_ID = "rougher";
const JOB_ID = "kpi-live";
const URL_BASE = `/#/d/${INFO.dataset}`;
const STEP = { timeout: 30_000 };
const SLOW = { timeout: 120_000 };
const CHECK_WINDOW_S = 20; // wall seconds of plant samples per KPI check (20x sim speed: ~7 sim minutes)
const MIN_ERROR_CHANGE = 0.02; // the control error must differ by at least 2 % after the retune

test.describe.configure({ mode: "serial" });
test.skip(ENV.E2E_L5_NOCODE !== "1", "nightly L5 only: needs live RougherSim (E2E_L5_NOCODE=1)");
test.setTimeout(300_000);
test.use({ locale: "en-US" });

type Nodes = { Gain: number; Ti: number; Pv: number; Sp: number; Rsp: number; Out: number; Mode: number };
type Reply = { status: number; body: any };

const pages = new Map<string, Page>();
const contexts: BrowserContext[] = [];
let proposalId = "";
let appliedGain = 0;
let appliedTi = 0;
let errorBefore = 0;

async function signedInPage(browser: Browser, name: string): Promise<Page> {
  const known = pages.get(name);
  if (known) return known;
  const context = await browser.newContext({ baseURL: ENV.E2E_BASE_URL, locale: "en-US" });
  contexts.push(context);
  const page = await context.newPage();
  await page.goto(`${URL_BASE}/overview`);
  await page.locator("#username").fill(name);
  await page.locator("#password").fill(USERS[name].password);
  await page.getByTestId("login-submit").click();
  await expect(page.getByTestId("role-badge-user")).toHaveAttribute("title", name, STEP);
  pages.set(name, page);
  return page;
}

/** One read-only API call from inside the page (session cookie); the spec never writes through it. */
async function apiGet(page: Page, path: string): Promise<Reply> {
  return page.evaluate(async (path) => {
    const reply = await fetch(`/api${path}`, { credentials: "same-origin" });
    const text = await reply.text();
    let body: unknown = text;
    try {
      body = text ? JSON.parse(text) : null;
    } catch {
      /* not JSON */
    }
    return { status: reply.status, body };
  }, path);
}

async function nodes(): Promise<Nodes> {
  return (await (await fetch(`${INFO.control_url}/nodes`)).json()) as Nodes;
}

/** Mean absolute control error |PV - RSP| of the loop over `seconds`, read from the plant itself. */
async function meanError(seconds: number): Promise<number> {
  const errors: number[] = [];
  const end = Date.now() + seconds * 1000;
  while (Date.now() < end) {
    const now = await nodes();
    errors.push(Math.abs(now.Pv - now.Rsp));
    await new Promise((done) => setTimeout(done, 250));
  }
  return errors.reduce((sum, value) => sum + value, 0) / errors.length;
}

/** The loop_kpi job of the runtime status (its last run advances while the KPI is live). */
async function kpiJob(page: Page): Promise<{ last_run_utc: string; kpi: Record<string, any> | null }> {
  const status = (await apiGet(page, "/runtime/status")).body;
  return status.jobs.find((job: { id: string }) => job.id === JOB_ID);
}

async function open(page: Page, view: string): Promise<void> {
  await page.goto(`${URL_BASE}/${view}`);
}

test.afterAll(async () => {
  for (const context of contexts) await context.close();
});

test("the project starts empty and this spec writes no file", async () => {
  expect(existsSync(join(INFO.root, "_site", "site.json"))).toBe(false);
  expect(existsSync(join(INFO.root, "_runtime", "jobs.json"))).toBe(false);
  // Only the GUI and the API may change the project: this spec imports no file-writing function.
  const source = readFileSync(fileURLToPath(import.meta.url), "utf-8");
  const imported = /import \{([^}]*)\} from "node:fs"/.exec(source)?.[1] ?? "";
  expect(imported.split(",").map((name) => name.trim()).sort()).toEqual(["existsSync", "readFileSync"]);
});

test("engineer adds the OPC UA source in the GUI and the connection test passes", async ({ browser }) => {
  const page = await signedInPage(browser, "e2e-engineer");
  await open(page, "catalogue");
  await page.getByTestId("mode-data-sources").click();
  await page.getByRole("button", { name: "Add source", exact: true }).click();
  const form = page.getByRole("form", { name: "Source" });
  await form.getByLabel("Id", { exact: true }).fill(SOURCE_ID);
  await form.getByLabel("Driver").selectOption("opcua");
  await form.getByLabel("Endpoint or folder").fill(INFO.opcua_endpoint);
  await form.getByRole("button", { name: "Test connection" }).click();
  await expect(form.getByRole("status").filter({ hasText: "Connection works" })).toBeVisible(SLOW);
  await expect(form.getByRole("status").filter({ hasText: /browse/ })).toBeVisible();
  await form.getByRole("button", { name: "Save", exact: true }).click();
  await expect(page.getByRole("region", { name: "Sources" }).getByText(SOURCE_ID)).toBeVisible(STEP);
});

test("engineer builds the catalogue from the source browse: preset roles and loops accepted", async ({ browser }) => {
  const page = await signedInPage(browser, "e2e-engineer");
  await open(page, "catalogue");
  await page.getByTestId("mode-from-source").click();
  await page.getByLabel("1. Source").selectOption(SOURCE_ID);
  await page.getByLabel("Start from a preset").selectOption("isa_suffix");
  await page.getByRole("button", { name: "Preview", exact: true }).click();
  const preview = page.getByRole("region", { name: "3. Preview" });
  await expect(preview.getByText(/tags matched/)).toBeVisible(SLOW);
  await expect(preview.getByText(new RegExp(`${INFO.loop}`)).first()).toBeVisible();
  // The loop tags are proposed (checked); the controller parameters are picked by hand for tuning.
  for (const tag of [INFO.gain_tag, INFO.ti_tag]) {
    await preview.getByRole("checkbox", { name: tag, exact: true }).check();
  }
  await expect(preview.getByRole("checkbox", { name: `${INFO.loop}.Pv`, exact: true })).toBeChecked();
  await preview.getByRole("button", { name: /^Import \d+ tags$/ }).click();
  await expect(preview.getByText(/Added \d+ tags, \d+ loops/)).toBeVisible(STEP);
  const site = (await apiGet(page, "/site")).body;
  expect(site.loops.map((loop: { id: string }) => loop.id)).toContain(INFO.loop);
  const tagIds = site.tags.map((tag: { id: string }) => tag.id);
  expect(tagIds).toEqual(expect.arrayContaining([INFO.gain_tag, INFO.ti_tag, `${INFO.loop}.Out`]));
});

test("engineer starts the live KPI job in the Runtime view and sees the live KPI", async ({ browser }) => {
  const page = await signedInPage(browser, "e2e-engineer");
  await open(page, "runtime");
  await expect(page.getByTestId("runtime-service-status")).toHaveText("running", SLOW);
  await page.getByTestId("runtime-form-id").fill(JOB_ID);
  await page.getByTestId("runtime-form-kind").selectOption("loop_kpi");
  await page.getByTestId("runtime-form-source").fill(SOURCE_ID);
  await page.getByTestId("runtime-form-targets").fill(INFO.loop);
  await page.getByTestId("runtime-form-period").fill("1");
  await page.getByTestId("runtime-form-window").fill("600");
  await page.getByTestId("runtime-create").click();
  await expect(page.getByTestId(`runtime-job-${JOB_ID}`)).toBeVisible(STEP);
  await open(page, "loops?mode=live");
  await page.getByTestId("live-loops").getByRole("button", { name: INFO.loop, exact: true }).click();
  const detail = page.getByRole("region", { name: `Live detail of ${INFO.loop}` });
  try {
    await expect(detail.getByText("Time in AUTO")).toBeVisible(SLOW);
  } catch (error) {
    // Say what the runtime saw, so the nightly report shows why no KPI arrived.
    const status = (await apiGet(page, "/runtime/status")).body;
    const log = (await apiGet(page, "/runtime/log?limit=3")).body;
    const shown = await page.getByTestId("live-loops").innerText().catch(() => "(no live-loops list)");
    throw new Error(`no live KPI: ${JSON.stringify(status)} ${JSON.stringify(log)}
${shown}
${error}`);
  }
  await expect(detail.getByText("Classification")).toBeVisible(STEP);
  expect((await kpiJob(page)).kpi?.[INFO.loop]).toMatchObject({ service_factor: expect.any(Number) });
});

test("lead raises the gateway to confirm in the GUI (one step at a time)", async ({ browser }) => {
  const lead = await signedInPage(browser, "e2e-lead");
  await open(lead, "gateway");
  const select = lead.getByTestId("gateway-mode-select");
  await expect(select).toBeVisible(STEP);
  await expect(lead.getByTestId("gateway-mode-chip")).toHaveText("advisory", STEP);
  await select.selectOption("dry_run");
  await expect(lead.getByTestId("gateway-mode-chip")).toHaveText("dry_run", STEP);
  await select.selectOption("confirm");
  await expect(lead.getByTestId("gateway-mode-chip")).toHaveText("confirm", STEP);
});

test("engineer proposes a tuning change from the Tuning view: it is queued in confirm mode", async ({ browser }) => {
  const page = await signedInPage(browser, "e2e-engineer");
  await page.goto(`${URL_BASE}/loops/${INFO.loop}/tuning`);
  const propose = page.getByTestId("tuning-propose-button");
  await expect(propose).toBeEnabled(SLOW);
  await propose.click();
  await page.getByTestId("tuning-propose-reason").fill("L5 no-code acceptance");
  await page.getByTestId("tuning-propose-submit").click();
  await expect(page.getByTestId("tuning-propose-result")).toContainText("Proposal created", STEP);
  await page.getByTestId("tuning-propose-link").click();
  const list = (await apiGet(page, `/tuning/proposals?loop_id=${INFO.loop}`)).body as any[];
  const mine = list.find((p) => p.status === "queued");
  expect(mine, JSON.stringify(list)).toBeDefined();
  proposalId = mine.id;
  appliedGain = mine.items.find((i: any) => i.param === "gain").to;
  appliedTi = mine.items.find((i: any) => i.param === "ti").to;
  expect(appliedGain).not.toBeCloseTo(INFO.initial_gain, 3);
  const before = await nodes();
  expect(before.Gain).toBeCloseTo(INFO.initial_gain, 3);
  errorBefore = await meanError(CHECK_WINDOW_S);
});

test("the proposal waits in the gateway queue; the lead approves it there", async ({ browser }) => {
  const lead = await signedInPage(browser, "e2e-lead");
  await open(lead, "gateway");
  const queued = lead.getByTestId(`gateway-pending-params-${proposalId}`);
  await expect(queued).toBeVisible(STEP);
  await queued.getByRole("link").click();
  await lead.getByTestId(`tuning-row-${proposalId}`).getByRole("button").click();
  await lead.getByTestId("tuning-approve").click();
  await lead.getByTestId("tuning-approve-check").check();
  await lead.getByTestId("tuning-approve-confirm").click();
  await expect.poll(async () => (await apiGet(lead, `/tuning/proposals/${proposalId}`)).body.status, STEP).toBe("applied");
});

test("the plant has the new parameters and the live KPI keeps updating", async ({ browser }) => {
  await expect.poll(async () => (await nodes()).Gain, STEP).toBeCloseTo(appliedGain, 2);
  await expect.poll(async () => (await nodes()).Ti, STEP).toBeCloseTo(appliedTi, 2);
  const page = await signedInPage(browser, "e2e-engineer");
  await open(page, "loops?mode=live");
  await page.getByTestId("live-loops").getByRole("button", { name: INFO.loop, exact: true }).click();
  await expect(page.getByRole("region", { name: `Live detail of ${INFO.loop}` }).getByText("Classification")).toBeVisible(STEP);
  const run = (await kpiJob(page)).last_run_utc;
  await expect.poll(async () => (await kpiJob(page)).last_run_utc, STEP).not.toBe(run);
  // The KPI of the plant itself changed with the tuning: the control error differs from before the write.
  const errorAfter = await meanError(CHECK_WINDOW_S);
  test.info().annotations.push({ type: "mean |PV-RSP|", description: `before ${errorBefore}, after ${errorAfter}` });
  expect(Math.abs(errorAfter - errorBefore) / errorBefore).toBeGreaterThan(MIN_ERROR_CHANGE);
});

test("engineer rolls back in the GUI, the lead approves and the previous parameters return", async ({ browser }) => {
  const engineer = await signedInPage(browser, "e2e-engineer");
  await open(engineer, "tuning");
  await engineer.getByTestId(`tuning-row-${proposalId}`).getByRole("button").click();
  await engineer.getByTestId("tuning-rollback").click();
  await engineer.getByTestId("tuning-rollback-reason").fill("L5 no-code rollback");
  await engineer.getByTestId("tuning-rollback-confirm").click();
  let rollbackId = "";
  await expect
    .poll(async () => {
      const list = (await apiGet(engineer, `/tuning/proposals?loop_id=${INFO.loop}`)).body as any[];
      const found = list.find((p) => p.rollback_of === proposalId);
      rollbackId = found?.id ?? "";
      return found?.status;
    }, STEP)
    .toBe("queued");
  const lead = await signedInPage(browser, "e2e-lead");
  await open(lead, "tuning");
  await lead.getByTestId(`tuning-row-${rollbackId}`).getByRole("button").click();
  await lead.getByTestId("tuning-approve").click();
  await lead.getByTestId("tuning-approve-check").check();
  await lead.getByTestId("tuning-approve-confirm").click();
  await expect.poll(async () => (await apiGet(lead, `/tuning/proposals/${rollbackId}`)).body.status, STEP).toBe("applied");
  await expect.poll(async () => (await nodes()).Gain, STEP).toBeCloseTo(INFO.initial_gain, 3);
  await expect.poll(async () => (await nodes()).Ti, STEP).toBeCloseTo(INFO.initial_ti, 3);
  // The audit shows both writes by the lead and the catalogue import by the engineer.
  const audit = (await apiGet(lead, "/gateway/audit?limit=1000")).body.records as Record<string, string>[];
  const writes = audit.filter((r) => r.event === "param_write");
  expect(writes.map((r) => r.proposal_id)).toEqual(expect.arrayContaining([proposalId, rollbackId]));
  expect(writes.every((r) => r.actor === "e2e-lead")).toBe(true);
});
