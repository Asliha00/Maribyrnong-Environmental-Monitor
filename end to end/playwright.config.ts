import { defineConfig, devices } from "@playwright/test";
import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";

/**
 * End-to-end tests against the PRODUCTION BUILD (vite preview, served with the exact
 * vercel.json headers including the CSP) and the real FastAPI backend on a SYNTHETIC
 * fixture database (backend/scripts/make_fixture_db.py): no council data needed, so CI can
 * run it too.
 *
 *   cd e2e && npm ci && npx playwright install chromium && npx playwright test
 *
 * Needs SEED_ANALYST_PASSWORD / SEED_ADMIN_PASSWORD, JWT_SECRET and
 * MFA_ENCRYPTION_KEY: read from the developer's .env (never committed) or the CI environment.
 */
const ROOT = join(import.meta.dirname, "..");
const FIXTURE_DB = join(import.meta.dirname, ".fixture.db");

// Local runs: take the needed values from .env; real environment variables win.
if (existsSync(join(ROOT, ".env"))) {
  for (const line of readFileSync(join(ROOT, ".env"), "utf-8").split(/\r?\n/)) {
    const match =
      /^\s*(SEED_[A-Z_]+|JWT_SECRET|MFA_ENCRYPTION_KEY)\s*=\s*(.*?)\s*$/.exec(
        line,
      );
    if (match && !process.env[match[1]]) process.env[match[1]] = match[2];
  }
}

// Relative to ROOT (the servers' working directory): no spaces, so no quoting. On Windows
// cmd.exe mangles a command line that starts with a quoted path and has more quotes later.
const python =
  process.platform === "win32" &&
  existsSync(join(ROOT, ".venv", "Scripts", "python.exe"))
    ? String.raw`.venv\Scripts\python.exe`
    : existsSync(join(ROOT, ".venv", "bin", "python"))
      ? ".venv/bin/python"
      : "python3";

const backendEnv = {
  ...(process.env as Record<string, string>),
  ENVIRONMENT: "development", // http://localhost: Secure cookies would be dropped
  APP_DATABASE_URL: "", // never a real database in browser tests
  SQLITE_PATH: FIXTURE_DB,
};

export default defineConfig({
  testDir: ".",
  testMatch: "*.spec.ts",
  fullyParallel: false,
  workers: 1, // one shared database and a 5-per-minute login limit
  retries: process.env.CI ? 1 : 0,
  reporter: [["list"]],
  use: { baseURL: "http://localhost:4173", trace: "retain-on-failure" },
  projects: [
    { name: "setup", testMatch: /auth.setup.ts/ },
    {
      name: "chromium",
      dependencies: ["setup"],
      testIgnore: /admin\.spec\.ts/,
      use: {
        ...devices["Desktop Chrome"],
        viewport: { width: 1366, height: 768 },
      },
    },
    {
      // Last: it registers a sensor and edits a threshold in the shared fixture database
      name: "admin",
      dependencies: ["chromium"],
      testMatch: /admin\.spec\.ts/,
      use: { ...devices["Desktop Chrome"] },
    },
  ],
  webServer: [
    {
      command: `${python} backend/scripts/make_fixture_db.py e2e/.fixture.db && ${python} -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000`,
      cwd: ROOT,
      env: backendEnv,
      url: "http://127.0.0.1:8000/api/health",
      reuseExistingServer: false,
      timeout: 120_000,
    },
    {
      command: "npm run build && npx vite preview",
      cwd: join(ROOT, "frontend"),
      url: "http://localhost:4173",
      reuseExistingServer: false,
      timeout: 120_000,
    },
  ],
});
