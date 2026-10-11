import { spawn } from "node:child_process";
import { existsSync } from "node:fs";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
if (!existsSync(resolve(root, "out/index.html"))) {
  console.error("No static export found. Run npm run build first, or use npm run dev:local for the full local rehearsal.");
  process.exit(1);
}
const port = Number(process.env.DEALFEED_PORT || 3001);
if (!Number.isInteger(port) || port < 1024 || port > 65535) throw new Error("DEALFEED_PORT must be between 1024 and 65535.");
const child = spawn("python3", ["-m", "http.server", String(port), "--bind", "127.0.0.1", "--directory", resolve(root, "out")], { stdio: "inherit" });
child.on("error", error => { console.error(error.message); process.exitCode = 1; });
child.on("exit", code => { process.exitCode = code ?? 0; });
process.on("SIGINT", () => child.kill("SIGTERM"));
process.on("SIGTERM", () => child.kill("SIGTERM"));
console.log(`DealFeed static export: http://127.0.0.1:${port}`);
