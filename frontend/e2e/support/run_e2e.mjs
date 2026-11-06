// One-command e2e run (`npm run e2e:all`): builds a temp data root with make_e2e_root.py, starts the
// API and Vite on free ports, then the OPC UA test server (wood_berry) and the crosscut_runtime service
// on that root, runs `playwright test` (extra CLI args are passed on) and always stops the servers.
// Only the temp directory is created and removed. Windows and Linux.
// E2E_AUTH=1 starts the API with authentication ON after creating a first admin with the auth CLI
// (E2E_ADMIN_USER / E2E_ADMIN_PASSWORD are passed to the specs); by default auth is off.
// E2E_GATEWAY=1 implies E2E_AUTH=1, adds one user per role (E2E_USERS) and starts the real Write
// Gateway stack (start_gateway_stack.py: OPC UA server, gateway process, control channel); its
// description is passed to the specs as E2E_GW_* variables (used by gateway-live.spec.ts).
import { spawn, spawnSync } from "node:child_process";
import { existsSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { connect, createServer } from "node:net";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const frontend = resolve(here, "../..");
const repo = resolve(frontend, "..");
// The e2e suite runs with auth disabled (specs do not log in); E2E_AUTH=1 turns it on for auth.spec.ts.
const GATEWAY_ON = process.env.E2E_GATEWAY === "1";
const AUTH_ON = process.env.E2E_AUTH === "1" || GATEWAY_ON;
const ROLE_USERS = [
  ["e2e-engineer", "engineer"],
  ["e2e-operator", "operator"],
  ["e2e-lead", "lead"],
  ["e2e-viewer", "viewer"],
];
const ADMIN_USER = "e2e-admin";
const ADMIN_PASSWORD = "e2e-admin-correct-horse-1";
const API_HEAD = "import sys,uvicorn;from pathlib import Path;from crosscut_api.app import create_app;" +
  "from crosscut_api.auth.sessions import AuthConfig;from crosscut_api.auth.passwords import ScryptParams;";
const API_RUN = "host='127.0.0.1',port=int(sys.argv[2]),log_level='warning')";
const API_CODE = API_HEAD + (AUTH_ON
  ? "uvicorn.run(create_app(Path(sys.argv[1]),auth_config=AuthConfig(scrypt=ScryptParams(n=1024))),"
  : "uvicorn.run(create_app(Path(sys.argv[1]),auth_enabled=False),") + API_RUN;

/** The interpreter: E2E_PYTHON, else the repo venv, else `python`. */
function findPython() {
  if (process.env.E2E_PYTHON) return process.env.E2E_PYTHON;
  for (const rel of [".venv/Scripts/python.exe", ".venv/bin/python"]) {
    if (existsSync(join(repo, rel))) return join(repo, rel);
  }
  return "python";
}

/** Asks the OS for a free TCP port. */
function freePort() {
  return new Promise((ok, fail) => {
    const server = createServer();
    server.once("error", fail);
    server.listen(0, "127.0.0.1", () => {
      const { port } = server.address();
      server.close(() => ok(port));
    });
  });
}

/** Polls `url` until it answers with a non-5xx status or `child` exits / the time is up. */
async function waitFor(url, child, label) {
  const deadline = Date.now() + 90_000;
  while (Date.now() < deadline) {
    if (child.exitCode !== null) throw new Error(`${label} exited early (code ${child.exitCode})`);
    try {
      if ((await fetch(url)).status < 500) return;
    } catch {
      /* not up yet */
    }
    await new Promise((r) => setTimeout(r, 300));
  }
  throw new Error(`${label} did not answer at ${url}`);
}

/** Stops a child process (and its tree on Windows). */
function stop(child) {
  if (child.exitCode !== null) return;
  if (process.platform === "win32") spawnSync("taskkill", ["/pid", String(child.pid), "/T", "/F"]);
  else child.kill("SIGTERM");
}

/** True when a TCP connection to 127.0.0.1:`port` succeeds. */
function canConnect(port) {
  return new Promise((ok) => {
    const socket = connect(port, "127.0.0.1");
    socket.once("connect", () => {
      socket.destroy();
      ok(true);
    });
    socket.once("error", () => ok(false));
  });
}

/** Polls until `port` accepts connections; throws if `child` exits or after 60 s. */
async function waitForPort(port, child, label) {
  const deadline = Date.now() + 60_000;
  while (Date.now() < deadline) {
    if (child.exitCode !== null) throw new Error(`${label} exited early (code ${child.exitCode})`);
    if (await canConnect(port)) return;
    await new Promise((r) => setTimeout(r, 300));
  }
  throw new Error(`${label} did not accept connections on port ${port}`);
}

/** Starts the OPC UA test server, then the runtime service on `root`; returns the OPC UA endpoint. */
async function startBackground(python, root, children) {
  const opcuaPort = await freePort();
  const opcua = spawn(python, ["-m", "crosscut_opcua.server", "--plant", "wood_berry", "--port", String(opcuaPort), "--speed", "20", "--tick", "0.05"], { stdio: "inherit" });
  children.push(opcua);
  await waitForPort(opcuaPort, opcua, "OPC UA server");
  children.push(spawn(python, ["-m", "crosscut_runtime", "--root", root, "--interval", "0.5"], { stdio: "inherit" }));
  return `opc.tcp://127.0.0.1:${opcuaPort}`;
}

/** Creates the first admin with `python -m crosscut_api.auth_cli init` (cheap scrypt cost). */
function initAdmin(python, root) {
  const passwordFile = join(dirname(root), "admin-password.txt");
  writeFileSync(passwordFile, `${ADMIN_PASSWORD}
`);
  const env = { ...process.env, CROSSCUT_AUTH_SCRYPT_N: "1024" };
  const args = ["-m", "crosscut_api.auth_cli", "init", "--root", root, "--username", ADMIN_USER, "--password-file", passwordFile];
  const done = spawnSync(python, args, { env, stdio: "inherit" });
  if (done.status !== 0) throw new Error("auth_cli init failed");
}

/** Adds one user per role with the auth CLI; returns {name: {role, password}}. */
function addRoleUsers(python, root) {
  const env = { ...process.env, CROSSCUT_AUTH_SCRYPT_N: "1024" };
  const users = {};
  for (const [name, role] of ROLE_USERS) {
    const password = `${role}-pass-e2e-123456`;
    const file = join(dirname(root), `${name}-password.txt`);
    writeFileSync(file, `${password}\n`);
    const args = ["-m", "crosscut_api.auth_cli", "add-user", "--root", root, "--username", name, "--roles", role, "--password-file", file];
    if (spawnSync(python, args, { env, stdio: "inherit" }).status !== 0) throw new Error(`add-user ${name} failed`);
    users[name] = { role, password };
  }
  return users;
}

/** Resolves with the first JSON line the child prints; rejects when it exits first or after 120 s. */
function firstJsonLine(child, label) {
  return new Promise((ok, fail) => {
    let buffer = "";
    const timer = setTimeout(() => fail(new Error(`${label} printed no description`)), 120_000);
    child.once("exit", (code) => fail(new Error(`${label} exited early (code ${code})`)));
    child.stdout.on("data", (chunk) => {
      buffer += chunk;
      const line = buffer.split(/\r?\n/).find((text) => text.startsWith("{"));
      if (line === undefined) return;
      clearTimeout(timer);
      ok(JSON.parse(line));
    });
  });
}

/** Starts the gateway stack on `root`; returns the E2E_GW_* variables for the specs. */
async function startGatewayStack(python, root, children) {
  const script = join(here, "start_gateway_stack.py");
  const stack = spawn(python, [script, "--root", root], { stdio: ["pipe", "pipe", "inherit"] });
  children.push(stack);
  const info = await firstJsonLine(stack, "gateway stack");
  return {
    E2E_GW_ROOT: info.root,
    E2E_GW_TAG: info.tag,
    E2E_GW_CONTROL_URL: info.control_url,
    E2E_GW_OPCUA: info.opcua_endpoint,
    E2E_GW_INITIAL_SP: String(info.initial_setpoint),
    E2E_GW_HOLD_OFF_S: String(info.hold_off_s),
    E2E_GW_PROPOSE_SCRIPT: join(here, "gateway_propose.py"),
  };
}

async function main() {
  const python = findPython();
  const root = join(mkdtempSync(join(tmpdir(), "crosscut-e2e-")), "data");
  const children = [];
  try {
    const made = spawnSync(python, [join(here, "make_e2e_root.py"), root], { stdio: "inherit" });
    if (made.status !== 0) throw new Error("make_e2e_root.py failed");
    if (AUTH_ON) initAdmin(python, root);
    const users = GATEWAY_ON ? addRoleUsers(python, root) : {};
    const [apiPort, uiPort] = [await freePort(), await freePort()];
    const api = spawn(python, ["-c", API_CODE, root, String(apiPort)], { stdio: "inherit" });
    children.push(api);
    const env = { ...process.env, CROSSCUT_API: `http://127.0.0.1:${apiPort}` };
    const vite = spawn(process.execPath, [join(frontend, "node_modules/vite/bin/vite.js"), "--host", "localhost", "--port", String(uiPort), "--strictPort"], { cwd: frontend, env, stdio: "inherit" });
    children.push(vite);
    const base = `http://localhost:${uiPort}`;
    await waitFor(`http://127.0.0.1:${apiPort}/docs`, api, "API");
    await waitFor(base, vite, "Vite");
    const opcuaEndpoint = await startBackground(python, root, children);
    const pw = join(frontend, "node_modules/@playwright/test/cli.js");
    const testEnv = { ...process.env, E2E_BASE_URL: base, E2E_DATA_ROOT: root, E2E_PYTHON: python, E2E_OPCUA_ENDPOINT: opcuaEndpoint };
    if (AUTH_ON) Object.assign(testEnv, { E2E_AUTH: "1", E2E_ADMIN_USER: ADMIN_USER, E2E_ADMIN_PASSWORD: ADMIN_PASSWORD });
    if (GATEWAY_ON) {
      Object.assign(testEnv, await startGatewayStack(python, root, children));
      Object.assign(testEnv, { E2E_GATEWAY: "1", E2E_USERS: JSON.stringify(users) });
    }
    const run = spawnSync(process.execPath, [pw, "test", ...process.argv.slice(2)], { cwd: frontend, env: testEnv, stdio: "inherit" });
    return run.status ?? 1;
  } finally {
    children.forEach(stop);
    await new Promise((r) => setTimeout(r, 500));
    try {
      rmSync(dirname(root), { recursive: true, force: true });
    } catch (error) {
      console.warn(`could not remove ${dirname(root)}: ${error.message}`);
    }
  }
}

main().then(
  (code) => process.exit(code),
  (error) => {
    console.error(error.message);
    process.exit(1);
  },
);
