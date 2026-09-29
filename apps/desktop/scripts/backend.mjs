// `npm run backend`: start the Python API on 127.0.0.1:8765 for browser-based development.
import { spawn } from "node:child_process";
import { existsSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

const backend = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../../backend");
const venv = process.platform === "win32" ? path.join(backend, ".venv", "Scripts", "python.exe") : path.join(backend, ".venv", "bin", "python");
const python = existsSync(venv) ? venv : process.platform === "win32" ? "python" : "python3";
const child = spawn(python, ["-m", "clipfactory.server"], { cwd: backend, stdio: "inherit" });
child.on("exit", (code) => process.exit(code ?? 0));
for (const sig of ["SIGINT", "SIGTERM"]) process.on(sig, () => child.kill(sig));
