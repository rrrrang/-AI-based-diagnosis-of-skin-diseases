import { expect, request, type Page } from "@playwright/test";
import { DoctorLoginIdentity, type WorkflowIdentity } from "../support/auth";

const API = process.env.SKINAI_E2E_API_URL || "http://127.0.0.1:18165";
const PNG_SIGNATURE = "89504e470d0a1a0a";

export async function assertGradcam({ doctorPage, caseId, analysis, doctorSession, patientSession,
  requireUnassignedDoctor = false }: {
  doctorPage: Page;
  caseId: string;
  analysis: { overlayAvailable?: boolean };
  doctorSession: WorkflowIdentity;
  patientSession: WorkflowIdentity;
  requireUnassignedDoctor?: boolean;
}) {
  expect(analysis.overlayAvailable, "A completed real-model run must persist its Grad-CAM image.").toBe(true);
  const endpoint = `${API}/api/cases/${encodeURIComponent(caseId)}/analysis-image`;
  const image = await doctorPage.request.get(endpoint, doctorSession.requestOptions());
  expect(image.status(), "The assigned doctor must be able to read the saved PNG.").toBe(200);
  const contentType = image.headers()["content-type"]?.split(";")[0].trim();
  expect(contentType).toBe("image/png");
  expect(image.headers()["cache-control"]).toContain("no-store");
  const bytes = await image.body();
  expect(bytes.length).toBeGreaterThan(8);
  expect(bytes.subarray(0, 8).toString("hex")).toBe(PNG_SIGNATURE);
  // Decode the authenticated response itself, not a screenshot or a placeholder.
  const decoded = await doctorPage.evaluate(async (base64) => {
    const png = new Image();
    png.src = `data:image/png;base64,${base64}`;
    await png.decode();
    return { width: png.naturalWidth, height: png.naturalHeight };
  }, bytes.toString("base64"));
  expect(decoded.width).toBeGreaterThan(0);
  expect(decoded.height).toBeGreaterThan(0);

  const anonymous = await request.newContext();
  let unassignedStatus: number | undefined;
  try {
    expect((await anonymous.get(endpoint)).status()).toBe(401);
    expect((await anonymous.get(endpoint, patientSession.requestOptions())).status()).toBe(403);
    if (requireUnassignedDoctor) {
      const login = process.env.SKINAI_E2E_OTHER_DOCTOR_LOGIN;
      const password = process.env.SKINAI_E2E_OTHER_DOCTOR_PASSWORD;
      if (!login || !password) throw new Error("Focused Grad-CAM checks require a separate isolated doctor account.");
      const otherDoctor = await new DoctorLoginIdentity(login, password).login(anonymous, API);
      unassignedStatus = (await anonymous.get(endpoint, otherDoctor.requestOptions())).status();
      expect(unassignedStatus, "An unassigned doctor must not learn whether this case has an image.").toBe(404);
      await otherDoctor.logout(anonymous, API);
    }
  } finally {
    await anonymous.dispose();
  }

  const displayed = doctorPage.getByRole("img", { name: "마스킹 이미지 (Grad-CAM)", exact: true });
  await expect(displayed).toBeVisible();
  await expect.poll(() => displayed.evaluate((img) => (img as HTMLImageElement).naturalWidth))
    .toBe(decoded.width);
  await expect.poll(() => displayed.evaluate((img) => (img as HTMLImageElement).naturalHeight))
    .toBe(decoded.height);
  // Record only non-sensitive measurements; never the image body, URL, or session.
  return {
    checked: {
      gradcam_overlay_available: true,
      gradcam_authenticated_png: true,
      gradcam_png_decoded: true,
      gradcam_unauthenticated_blocked: true,
      gradcam_patient_blocked: true,
      gradcam_visible_in_doctor_ui: true,
      ...(requireUnassignedDoctor ? { gradcam_unassigned_doctor_blocked: true } : {}),
    },
    gradcam: {
      http_status: 200,
      content_type: contentType,
      byte_length: bytes.length,
      width: decoded.width,
      height: decoded.height,
      ui_natural_width: decoded.width,
      ui_natural_height: decoded.height,
      anonymous_status: 401,
      patient_status: 403,
      ...(requireUnassignedDoctor ? { unassigned_doctor_status: unassignedStatus } : {}),
    },
  };
}
