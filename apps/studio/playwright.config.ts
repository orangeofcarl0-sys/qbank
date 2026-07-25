import { defineConfig } from "playwright/test";

export default defineConfig({
  testDir: "tests/browser",
  timeout: 60_000,
  expect: { timeout: 15_000 },
  use: {
    baseURL: "http://127.0.0.1:1420",
    viewport: { width: 1480, height: 900 },
    colorScheme: "light",
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
  },
  webServer: {
    command: "npm run dev -- --host 127.0.0.1",
    url: "http://127.0.0.1:1420",
    reuseExistingServer: false,
    timeout: 120_000,
  },
});
