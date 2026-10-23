import { defineConfig, devices } from "@playwright/test";

// Smoke test against the real API serving the built screen and a run bundle
// recorded with the fake model (free, deterministic, no network).
const PORT = 8765;

export default defineConfig({
  testDir: "e2e",
  timeout: 30_000,
  use: { baseURL: `http://127.0.0.1:${PORT}`, trace: "retain-on-failure" },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: {
    command:
      "cd .. && (test -f demo/match.jsonl || uv run python -m engine.generate --demo --out demo) " +
      "&& uv run python -m agents.live.record --fake --out runs/e2e " +
      `&& RUNS_DIR=runs uv run uvicorn stream.api:app --port ${PORT}`,
    url: `http://127.0.0.1:${PORT}/api/runs`,
    timeout: 180_000,
    reuseExistingServer: !process.env.CI,
  },
});
