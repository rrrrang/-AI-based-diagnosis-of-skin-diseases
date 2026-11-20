import { defineConfig } from "@playwright/test";
import { fileURLToPath } from "node:url";
import path from "node:path";

const patientRoot = path.dirname(fileURLToPath(import.meta.url));
const doctorRoot = path.resolve(patientRoot, "../doctor-frontend");
const outputRoot = process.env.SKINAI_E2E_OUTPUT;
if (!outputRoot) throw new Error("SKINAI_E2E_OUTPUT must name the isolated run directory.");
function localEndpoint(name: string, fallback: string) {
  const url = new URL(process.env[name] || fallback);
  if (url.protocol !== "http:" || url.hostname !== "127.0.0.1" || !url.port ||
      url.username || url.password || url.pathname !== "/" || url.search || url.hash) {
    throw new Error(`${name} must be an HTTP loopback origin with an explicit port.`);
  }
  return url;
}
const api = localEndpoint("SKINAI_E2E_API_URL", "http://127.0.0.1:18165");
const patient = localEndpoint("SKINAI_E2E_PATIENT_URL", "http://127.0.0.1:18166");
const doctor = localEndpoint("SKINAI_E2E_DOCTOR_URL", "http://127.0.0.1:18167");
if (new Set([api.port, patient.port, doctor.port]).size !== 3) {
  throw new Error("The isolated API, patient and doctor previews require distinct ports.");
}

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
    baseURL: patient.origin,
    viewport: { width: 390, height: 844 },
    trace: "off",
    video: "off",
    screenshot: "off",
  },
  webServer: [
    {
      command: `npm run preview -- --outDir dist-e2e --host 127.0.0.1 --port ${patient.port} --strictPort`,
      cwd: patientRoot,
      env: { SKINAI_API_TARGET: api.origin },
      url: patient.origin,
      reuseExistingServer: false,
      timeout: 60_000,
    },
    {
      command: `npm run preview -- --outDir dist-e2e --host 127.0.0.1 --port ${doctor.port} --strictPort`,
      cwd: doctorRoot,
      env: { SKINAI_API_TARGET: api.origin },
      url: doctor.origin,
      reuseExistingServer: false,
      timeout: 60_000,
    },
  ],
});
