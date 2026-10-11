// A self-contained rehearsal: Next.js + FastAPI + SQLite. No cloud credentials needed.
import { spawn } from "node:child_process";
import { existsSync } from "node:fs";
import { createServer } from "node:net";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const python = resolve(root, process.platform === "win32" ? ".venv/Scripts/python.exe" : ".venv/bin/python");
const next = resolve(root, "node_modules/next/dist/bin/next");
const frontendPort = Number(process.env.DEALFEED_PORT || 3001);
const apiPort = Number(process.env.DEALFEED_API_PORT || 8000);

if (!existsSync(python) || !existsSync(next)) {
  console.error("Install dependencies first: npm ci; python3 -m venv .venv; .venv/bin/pip install -r backend/requirements.txt");
  process.exit(1);
}
for (const port of [frontendPort, apiPort]) {
  if (!Number.isInteger(port) || port < 1024 || port > 65535) throw new Error("Use ports between 1024 and 65535.");
  try {
    await new Promise((done, fail) => {
      const server = createServer();
      server.once("error", fail);
      server.listen(port, "127.0.0.1", () => server.close(done));
    });
  } catch {
    console.error(`Port ${port} is unavailable. Set DEALFEED_PORT or DEALFEED_API_PORT to a free port.`);
    process.exit(1);
  }
}
if (frontendPort === apiPort) throw new Error("Frontend and API ports must differ.");

const origin = `http://127.0.0.1:${frontendPort}`;
const apiUrl = `http://127.0.0.1:${apiPort}`;
const localEnv = { ...process.env, AI_MODE: "rehearsal", DEMO_AUTH_ENABLED: "true", ALLOWED_ORIGIN: origin, DATABASE_PATH: resolve(root, ".local/dealfeed.sqlite") };
// This command always runs locally, even if cloud configuration exists in the shell.
for (const key of ["TABLE_NAME", "BUCKET_NAME", "AWS_LAMBDA_FUNCTION_NAME", "AKAMAI_API_KEY", "AKAMAI_BASE_URL", "AKAMAI_MODEL"]) delete localEnv[key];

const children = [];
let stopping = false;
function stop(code = 0) {
  if (stopping) return;
  stopping = true;
  process.exitCode = code;
  for (const child of children) child.kill("SIGTERM");
}
function run(command, args, env) {
  const child = spawn(command, args, { cwd: root, env, stdio: "inherit" });
  children.push(child);
  child.on("error", error => { console.error(error.message); stop(1); });
  child.on("exit", code => { if (!stopping) stop(code ?? 1); });
  return child;
}
process.on("SIGINT", () => stop());
process.on("SIGTERM", () => stop());
run(python, ["-m", "uvicorn", "backend.app:app", "--host", "127.0.0.1", "--port", String(apiPort)], localEnv);

let ready = false;
for (let attempt = 0; attempt < 100 && !stopping; attempt++) {
  try {
    const response = await fetch(`${apiUrl}/health`, { signal: AbortSignal.timeout(500) });
    const health = await response.json();
    if (response.ok && health.mode === "rehearsal" && health.storage === "sqlite") { ready = true; break; }
  } catch { /* API is still starting. */ }
  await new Promise(done => setTimeout(done, 200));
}
if (!ready) {
  console.error("The local API did not start. Review its output above.");
  stop(1);
} else {
  console.log(`\nDealFeed local rehearsal: ${origin}\nAPI: ${apiUrl}\nStorage: .local/dealfeed.sqlite\nSample briefs only — Akamai and AWS are disconnected.\nPress Ctrl+C to stop both services.\n`);
  run(process.execPath, [next, "dev", "--hostname", "127.0.0.1", "--port", String(frontendPort)], { ...localEnv, NODE_ENV: "development", NEXT_PUBLIC_API_URL: apiUrl });
}
