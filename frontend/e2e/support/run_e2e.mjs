// One-command e2e run (`npm run e2e:all`): builds a temp data root with make_e2e_root.py, starts the
// API and Vite on free ports, then the OPC UA test server (wood_berry) and the crosscut_runtime service
// on that root, runs `playwright test` (extra CLI args are passed on) and always stops the servers.
// Only the temp directory is created and removed. Windows and Linux.
// E2E_AUTH=1 starts the API with authentication ON after creating a first admin with the auth CLI
// (E2E_ADMIN_USER / E2E_ADMIN_PASSWORD are passed to the specs); by default auth is off.
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
const AUTH_ON = process.env.E2E_AUTH === "1";
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

async function main() {
  const python = findPython();
  const root = join(mkdtempSync(join(tmpdir(), "crosscut-e2e-")), "data");
  const children = [];
  try {
    const made = spawnSync(python, [join(here, "make_e2e_root.py"), root], { stdio: "inherit" });
    if (made.status !== 0) throw new Error("make_e2e_root.py failed");
    if (AUTH_ON) initAdmin(python, root);
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
