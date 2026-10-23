// One-command e2e run (`npm run e2e:all`): builds a temp data root with make_e2e_root.py, starts the
// API and Vite on free ports, runs `playwright test` (extra CLI args are passed on) and always
// stops the servers. Only the temp directory is created and removed. Windows and Linux.
import { spawn, spawnSync } from "node:child_process";
import { existsSync, mkdtempSync, rmSync } from "node:fs";
import { createServer } from "node:net";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const frontend = resolve(here, "../..");
const repo = resolve(frontend, "..");
const API_CODE = "import sys,uvicorn;from pathlib import Path;from crosscut_api.app import create_app;" +
  "uvicorn.run(create_app(Path(sys.argv[1])),host='127.0.0.1',port=int(sys.argv[2]),log_level='warning')";

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

async function main() {
  const python = findPython();
  const root = join(mkdtempSync(join(tmpdir(), "crosscut-e2e-")), "data");
  const children = [];
  try {
    const made = spawnSync(python, [join(here, "make_e2e_root.py"), root], { stdio: "inherit" });
    if (made.status !== 0) throw new Error("make_e2e_root.py failed");
    const [apiPort, uiPort] = [await freePort(), await freePort()];
    const api = spawn(python, ["-c", API_CODE, root, String(apiPort)], { stdio: "inherit" });
    children.push(api);
    const env = { ...process.env, CROSSCUT_API: `http://127.0.0.1:${apiPort}` };
    const vite = spawn(process.execPath, [join(frontend, "node_modules/vite/bin/vite.js"), "--host", "localhost", "--port", String(uiPort), "--strictPort"], { cwd: frontend, env, stdio: "inherit" });
    children.push(vite);
    const base = `http://localhost:${uiPort}`;
    await waitFor(`http://127.0.0.1:${apiPort}/docs`, api, "API");
    await waitFor(base, vite, "Vite");
    const pw = join(frontend, "node_modules/@playwright/test/cli.js");
    const testEnv = { ...process.env, E2E_BASE_URL: base, E2E_DATA_ROOT: root, E2E_PYTHON: python };
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
