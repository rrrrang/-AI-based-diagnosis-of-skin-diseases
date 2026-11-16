import { defineConfig } from "@playwright/test";
import path from "node:path";
const output = process.env.SKINAI_E2E_OUTPUT;
if (!output) throw new Error("SKINAI_E2E_OUTPUT is required for packaged-image checks");
// Reuse the proven workflow against four Docker images; no Vite server or rebuild.
export default defineConfig({
  testDir: "./tests/workflow",
  workers: 1,
  retries: 0,
  forbidOnly: true,
  timeout: 420_000,
  expect: { timeout: 15_000 },
  outputDir: path.join(output, "playwright-results"),
  reporter: [["list"], ["json", { outputFile: path.join(output, "playwright-result.json") }]],
  use: {
    browserName: "chromium",
    actionTimeout: 20_000,
    navigationTimeout: 30_000,
    baseURL: "http://127.0.0.1:18166",
    viewport: { width: 390, height: 844 },
    trace: "off", video: "off", screenshot: "off",
  },
});
