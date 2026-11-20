import { defineConfig } from "@playwright/test";
import workflowConfig from "../../playwright.workflow.config";
import { fileURLToPath } from "node:url";
import path from "node:path";

// Explicit diagnostic entry point. The normal full workflow does not discover
// *.focused.ts, and its ensemble display assertion remains mandatory.
export default defineConfig({
  ...workflowConfig,
  testDir: path.dirname(fileURLToPath(import.meta.url)),
  testMatch: "gradcam.focused.ts",
});
