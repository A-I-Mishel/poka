import { defineConfig } from "@playwright/test";
import * as path from "node:path";

// E2E smoke for the split UI: real backend (open mode, throwaway data dir)
// + real Vite dev server. Catches runtime ReferenceErrors and broken wiring
// that unit tests and the bundler cannot see.
//
// Backend python: .venv on Windows dev machines, PATH python elsewhere
// (CI installs requirements into system python; override with E2E_PYTHON).
const PY =
  process.env.E2E_PYTHON ??
  (process.platform === "win32" ? ".\\.venv\\Scripts\\python.exe" : "python3");

export default defineConfig({
  testDir: "e2e",
  timeout: 90_000,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? "github" : "list",
  use: {
    baseURL: "http://localhost:5173",
    trace: "retain-on-failure",
  },
  webServer: [
    {
      command: `${PY} -m uvicorn backend.main:app --host 127.0.0.1 --port 8000`,
      cwd: "..",
      env: {
        PLUTO_AUTH_MODE: "open",
        // Absolute: a relative PLUTO_DATA_DIR would resolve against the
        // backend's working directory and scatter throwaway e2e data
        // outside the repo (projects/.e2e-data). Keep it in ./.e2e-data.
        // (import.meta.dirname: __dirname does not exist in ESM configs.)
        PLUTO_DATA_DIR: path.resolve(import.meta.dirname, "../.e2e-data"),
        PLUTO_FRONTEND_ORIGIN: "http://localhost:5173",
      },
      url: "http://127.0.0.1:8000/api/health",
      timeout: 120_000,
      reuseExistingServer: !process.env.CI,
      stdout: "pipe",
    },
    {
      command: "npm run dev -- --port 5173 --strictPort",
      url: "http://localhost:5173/",
      timeout: 120_000,
      reuseExistingServer: !process.env.CI,
    },
  ],
});
