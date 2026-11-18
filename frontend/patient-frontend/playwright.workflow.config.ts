import { defineConfig } from "@playwright/test";
import { fileURLToPath } from "node:url";
import path from "node:path";

const patientRoot = path.dirname(fileURLToPath(import.meta.url));
const doctorRoot = path.resolve(patientRoot, "../doctor-frontend");
const outputRoot = process.env.SKINAI_E2E_OUTPUT;
if (!outputRoot) throw new Error("SKINAI_E2E_OUTPUT must name the isolated run directory.");

// The runner builds both apps with VITE_SKINAI_API=true into dist-e2e first.
// Existing development previews and Jenkins UI tests use different ports.
export default defineConfig({
  testDir: "./tests/workflow",
  workers: 1,
  retries: 0,
  forbidOnly: true,
  timeout: 420_000,
  expect: { timeout: 15_000 },
  outputDir: path.join(outputRoot, "playwright-results"),
  reporter: [
    ["list"],
    ["json", { outputFile: path.join(outputRoot, "playwright-result.json") }],
  ],
  use: {
    browserName: "chromium",
    actionTimeout: 20_000,
    navigationTimeout: 30_000,
    baseURL: "http://127.0.0.1:18166",
    viewport: { width: 390, height: 844 },
    trace: "off",
    video: "off",
    screenshot: "off",
  },
  webServer: [
    {
      command: "npm run preview -- --outDir dist-e2e --host 127.0.0.1 --port 18166 --strictPort",
      cwd: patientRoot,
      env: { SKINAI_API_TARGET: "http://127.0.0.1:18165" },
      url: "http://127.0.0.1:18166",
      reuseExistingServer: false,
      timeout: 60_000,
    },
    {
      command: "npm run preview -- --outDir dist-e2e --host 127.0.0.1 --port 18167 --strictPort",
      cwd: doctorRoot,
      env: { SKINAI_API_TARGET: "http://127.0.0.1:18165" },
      url: "http://127.0.0.1:18167",
      reuseExistingServer: false,
      timeout: 60_000,
    },
  ],
});