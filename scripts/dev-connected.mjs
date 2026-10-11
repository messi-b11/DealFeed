// Connected development with the user's inference settings; never silently switches AI modes.
import { spawn } from "node:child_process";
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { createServer } from "node:net";
import { randomBytes } from "node:crypto";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import nextEnv from "@next/env";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
nextEnv.loadEnvConfig(root, true);
const python = resolve(root, process.platform === "win32" ? ".venv/Scripts/python.exe" : ".venv/bin/python");
const frontendPort = Number(process.env.DEALFEED_PORT || 3001);
const apiPort = Number(process.env.DEALFEED_API_PORT || 8000);
if (!existsSync(python)) throw new Error("Install backend dependencies in .venv first.");
for (const port of [frontendPort, apiPort]) {
  if (!Number.isInteger(port) || port < 1024 || port > 65535) throw new Error("Use ports between 1024 and 65535.");
  await new Promise((done, fail) => {
    const server = createServer(); server.once("error", fail);
    server.listen(port, "127.0.0.1", () => server.close(done));
  });
}
if (frontendPort === apiPort) throw new Error("Frontend and API ports must differ.");
mkdirSync(resolve(root, ".local"), { recursive: true });
const secretFile = resolve(root, ".local/session-secret");
if (!existsSync(secretFile)) writeFileSync(secretFile, randomBytes(32).toString("hex"), { mode: 0o600 });
const origin = `http://127.0.0.1:${frontendPort}`;
const apiUrl = `http://127.0.0.1:${apiPort}`;
const env = {
  ...process.env,
  AI_MODE: process.env.AI_MODE || "live",
  DEMO_AUTH_ENABLED: "true",
  ASYNC_ANALYSIS: "true",
  ALLOWED_ORIGIN: origin,
  DATABASE_PATH: resolve(root, ".local/dealfeed.sqlite"),
  SESSION_SECRET: process.env.SESSION_SECRET || readFileSync(secretFile, "utf8").trim(),
};
for (const key of ["TABLE_NAME", "BUCKET_NAME", "AWS_LAMBDA_FUNCTION_NAME"]) delete env[key];
const children = []; let stopping = false;
function stop(code = 0) { if (stopping) return; stopping = true; process.exitCode = code; for (const child of children) child.kill("SIGTERM"); }
function run(command, args, environment) {
  const child = spawn(command, args, { cwd: root, env: environment, stdio: "inherit" }); children.push(child);
  child.on("error", error => { console.error(error.message); stop(1); });
  child.on("exit", code => { if (!stopping) stop(code ?? 1); }); return child;
}
process.on("SIGINT", () => stop()); process.on("SIGTERM", () => stop());
run(python, ["-m", "uvicorn", "backend.app:app", "--host", "127.0.0.1", "--port", String(apiPort)], env);
let ready = false;
for (let attempt = 0; attempt < 100 && !stopping; attempt++) {
  try { const response = await fetch(`${apiUrl}/health`, { signal: AbortSignal.timeout(500) }); if (response.ok) { ready = true; break; } } catch {}
  await new Promise(done => setTimeout(done, 200));
}
if (!ready) { console.error("The API did not start."); stop(1); }
else {
  console.log(`DealFeed: ${origin}\nAPI: ${apiUrl}\nAnalysis mode: ${env.AI_MODE}\nPress Ctrl+C to stop.`);
  run(process.execPath, [resolve(root, "node_modules/next/dist/bin/next"), "dev", "--hostname", "127.0.0.1", "--port", String(frontendPort)], { ...env, NODE_ENV: "development", DEALFEED_API_ORIGIN: apiUrl, NEXT_PUBLIC_API_URL: "/api" });
}
