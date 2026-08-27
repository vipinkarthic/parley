import { defineConfig, devices } from "@playwright/test";
import { existsSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";

/**
 * Ports deliberately off the defaults. Vipin's own dev stack runs the API on
 * 8100 and Next on 3000; a test run that grabbed those would either collide
 * with it or, worse, quietly point the suite at a backend holding real data.
 */
const API_PORT = 8111;
const WEB_PORT = 3111;
const API_BASE = `http://127.0.0.1:${API_PORT}`;
const WEB_BASE = `http://127.0.0.1:${WEB_PORT}`;

const BACKEND_DIR = resolve(__dirname, "../backend");
const FRONTEND_DIR = resolve(__dirname, "../frontend");

/**
 * Prefer the checked-out virtualenv locally, fall back to whatever python is
 * on PATH in CI (where the workflow has already pip-installed into the job's
 * own environment).
 */
const VENV_PYTHON = join(BACKEND_DIR, ".venv/bin/python");
const PYTHON = existsSync(VENV_PYTHON) ? VENV_PYTHON : "python3";

/**
 * A fresh SQLite file per run, in the OS temp dir rather than the repo.
 * The database is disposable by construction: `start-backend` deletes it
 * before migrating, so a run never inherits the previous run's accounts and
 * "this email is already registered" cannot become a flake.
 */
const E2E_DB = join(tmpdir(), "parley-e2e.db");

const BACKEND_ENV = {
  APP_ENV: "development",
  DATABASE_URL: `sqlite:///${E2E_DB}`,
  // Empty SMTP credentials force EMAIL_ENABLED=False, which is what makes the
  // OTP come back in the response body and on the page. The signup flow is
  // therefore testable without a mail server, and no test can send real mail.
  SMTP_USER: "",
  SMTP_PASS: "",
  JWT_SECRET: "e2e-secret-not-used-anywhere-real",
  SEED_SAMPLE_DATA: "false",
  FRONTEND_URL: WEB_BASE,
  CORS_ORIGINS: `${WEB_BASE},http://localhost:${WEB_PORT}`,
  PYTHONUNBUFFERED: "1",
};

export default defineConfig({
  testDir: "./tests",
  // Each spec drives two live participants through a WebSocket room; running
  // specs in parallel against one backend made ordering assertions racy for
  // no wall-clock win worth having at three files.
  fullyParallel: false,
  workers: 1,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  timeout: 90_000,
  expect: { timeout: 15_000 },
  reporter: process.env.CI
    ? [["list"], ["html", { open: "never" }], ["json", { outputFile: "results.json" }]]
    : [["list"], ["html", { open: "never" }]],

  use: {
    baseURL: WEB_BASE,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
    actionTimeout: 15_000,
  },

  projects: [
    {
      name: "firefox",
      use: {
        ...devices["Desktop Firefox"],
        /**
         * Zen is a Gecko fork, but Playwright's Firefox support needs Gecko
         * patched with its Juggler protocol, which ships only in Playwright's
         * own build - there is no executablePath escape hatch the way there is
         * for Chromium's CDP. This is the same engine family as Zen, driven by
         * the one build that can actually be automated.
         */
        launchOptions: {
          firefoxUserPrefs: {
            // A synthetic camera and microphone, so getUserMedia resolves on a
            // headless machine with no hardware. Without this the pre-join
            // screen sits on "Preparing devices..." forever.
            "media.navigator.streams.fake": true,
            "media.navigator.permission.disabled": true,
            "permissions.default.camera": 1,
            "permissions.default.microphone": 1,
          },
        },
      },
    },
  ],

  webServer: [
    {
      // Migrations first: the app calls _require_schema() on startup and
      // refuses to boot against an empty database, so `uvicorn` alone would
      // exit before Playwright ever connected.
      command: `rm -f ${E2E_DB} && ${PYTHON} -m alembic upgrade head && ${PYTHON} -m uvicorn app.main:app --host 127.0.0.1 --port ${API_PORT}`,
      cwd: BACKEND_DIR,
      url: `${API_BASE}/healthz`,
      reuseExistingServer: false,
      timeout: 120_000,
      stdout: "pipe",
      stderr: "pipe",
      env: BACKEND_ENV,
    },
    {
      // NEXT_PUBLIC_* is inlined at build time, so the build and the server
      // both have to see the test API base - building with the developer's
      // .env.local would bake in the Tailscale address and every request from
      // the test browser would leave the harness.
      command: `npm run build && npx next start --hostname 127.0.0.1 --port ${WEB_PORT}`,
      cwd: FRONTEND_DIR,
      url: WEB_BASE,
      reuseExistingServer: false,
      timeout: 300_000,
      stdout: "pipe",
      stderr: "pipe",
      env: {
        NEXT_PUBLIC_API_BASE: API_BASE,
        NEXT_TELEMETRY_DISABLED: "1",
      },
    },
  ],
});

export { API_BASE, WEB_BASE, E2E_DB };
