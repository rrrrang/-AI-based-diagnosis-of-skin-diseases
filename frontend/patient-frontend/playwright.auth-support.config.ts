import { defineConfig } from "@playwright/test";

// Helper-only tests: no login endpoint, browser, server, or deployment is used.
// Existing workflow/release configurations do not collect this directory.
export default defineConfig({
  testDir: "./tests/auth-support",
  workers: 1,
  retries: 0,
  forbidOnly: true,
  reporter: "list",
  outputDir: "./test-results/auth-support",
  use: { trace: "off", video: "off", screenshot: "off" },
});
