import { test, expect } from "@playwright/test";
import { existsSync, mkdirSync, writeFileSync } from "node:fs";
import path from "node:path";
import { doctorIdentityFromEnvironment, patientIdentityFromIntake } from "../support/auth";
import { DoctorWorkflowPage, PatientWorkflowPage } from "./workflow.pages";
import { assertGradcam } from "./gradcam.assertions";

const API = process.env.SKINAI_E2E_API_URL || "http://127.0.0.1:18165";
const MODEL_KEYS = ["mobilenet", "resnet50", "yolo"];
const CANDIDATE_KEYS = ["psoriasis", "atopic_dermatitis", "acne", "normal", "rosacea", "seborrheic_dermatitis"];
const CANDIDATE_LABELS = ["건선", "아토피", "여드름", "정상", "주사", "지루"];
type Analysis = {
  overlayAvailable?: boolean;
  analyzedPhotoIndex: number;
  modelVersions: Record<string, string>;
  models: Record<string, { candidate: string; score: number } | null>;
  yolo_disease_scores: { class_id: number; name: string; label: string; detected: boolean; score: number | null }[];
};

for (const photoCount of [2, 3] as const) {
  test(`Grad-CAM 전용: 사진 ${photoCount}장 실제 분석 → 저장·권한·화면`, async ({ page, browser }) => {
    const sample = process.env.SKINAI_E2E_SAMPLE;
    const output = process.env.SKINAI_E2E_OUTPUT;
    if (!sample || !output) throw new Error("A prepared non-personal sample and isolated evidence directory are required.");
    expect(existsSync(sample)).toBe(true);
    const doctorContext = await browser.newContext({ viewport: { width: 1440, height: 1080 } });
    const doctorPage = await doctorContext.newPage();
    const patient = new PatientWorkflowPage(page);
    const doctor = new DoctorWorkflowPage(doctorPage);
    const started = Date.now();
    const patientName = `CI이미지${photoCount}-${started.toString(36)}`;
    const patientPhone = "010" + String(started + photoCount).slice(-8);
    try {
      const patientSession = await patient.login(patientPhone, patientName);
      const bookingDate = await patient.reserveDoctor();
      await patient.photosAndSymptoms(sample, photoCount);
      await patient.fillPatient(patientName);
      const intakeResponse = page.waitForResponse((r) =>
        new URL(r.url()).pathname === "/api/cases" && r.request().method() === "POST");
      const analysisResponse = page.waitForResponse((r) =>
        /^\/api\/cases\/[^/]+\/analyze$/.test(new URL(r.url()).pathname) && r.request().method() === "POST");
      await page.getByRole("button", { name: "AI 분석 요청", exact: true }).click();
      const [intake, queued] = await Promise.all([intakeResponse, analysisResponse]);
      expect(intake.status()).toBe(201);
      const { caseId } = patientIdentityFromIntake(await intake.json());
      expect(new URL(queued.url()).pathname).toBe(`/api/cases/${caseId}/analyze`);
      expect(queued.status()).toBe(202);
      const doctorSession = await doctor.connect(doctorIdentityFromEnvironment(), bookingDate, patientName);
      let analysis: Analysis | undefined;
      await expect.poll(async () => {
        const response = await doctorPage.request.get(`${API}/api/cases/${caseId}`, doctorSession.requestOptions());
        expect(response.status()).toBe(200);
        const detail = await response.json() as { aiState: string; analysis?: Analysis };
        analysis = detail.analysis;
        return detail.aiState;
      }, { timeout: 240_000, intervals: [1000, 3000, 5000],
        message: "The real model worker must complete the submitted close-up." }).toBe("완료");
      expect(analysis).toBeTruthy();
      const complete = analysis!;
      expect(complete.analyzedPhotoIndex).toBe(1);
      expect(Object.keys(complete.models).sort()).toEqual([...MODEL_KEYS].sort());
      expect(Object.keys(complete.modelVersions).sort()).toEqual([...MODEL_KEYS].sort());
      for (const name of MODEL_KEYS) {
        expect(complete.modelVersions[name]).toMatch(/^[a-f0-9]{64}$/);
        const prediction = complete.models[name];
        if (name !== "yolo") expect(prediction).not.toBeNull();
        if (prediction !== null) {
          expect(CANDIDATE_KEYS).toContain(prediction.candidate);
          expect(Number.isFinite(prediction.score)).toBe(true);
          expect(prediction.score).toBeGreaterThanOrEqual(0);
          expect(prediction.score).toBeLessThanOrEqual(1);
        }
      }
      expect(complete.yolo_disease_scores).toHaveLength(6);
      for (const [index, row] of complete.yolo_disease_scores.entries()) {
        expect(row.class_id).toBe(index);
        expect(row.name).toBe(CANDIDATE_KEYS[index]);
        expect(row.label).toBe(CANDIDATE_LABELS[index]);
        expect(typeof row.detected).toBe("boolean");
        if (row.detected) {
          expect(typeof row.score).toBe("number");
          expect(Number.isFinite(row.score)).toBe(true);
          expect(row.score).toBeGreaterThanOrEqual(0.25);
          expect(row.score).toBeLessThanOrEqual(1);
        } else expect(row.score).toBeNull();
      }
      const top = complete.yolo_disease_scores.filter((row) => row.detected)
        .sort((a, b) => b.score! - a.score! || a.class_id - b.class_id)[0];
      expect(complete.models.yolo).toEqual(top ? { candidate: top.name, score: top.score } : null);

      const refreshed = doctorPage.waitForResponse((r) =>
        new URL(r.url()).pathname === "/api/cases" && r.request().method() === "GET");
      await doctorPage.getByRole("button", { name: "예약 정보 새로고침", exact: true }).click();
      expect((await refreshed).status()).toBe(200);
      await doctor.openPatient(patientName);
      const evidence = await assertGradcam({ doctorPage, caseId, analysis: complete,
        doctorSession, patientSession, requireUnassignedDoctor: true });
      await doctorSession.logout(doctorPage.request, API);
      await patientSession.logout(page.request, API);
      mkdirSync(output, { recursive: true });
      writeFileSync(path.join(output, `gradcam-${photoCount}-photos.json`), JSON.stringify({
        status: "passed", verification_scope: "gradcam-only", photo_count: photoCount,
        model_keys: MODEL_KEYS, model_versions: complete.modelVersions,
        checked: { three_real_model_results: true, yolo_six_class_response_checked: true, ...evidence.checked },
        gradcam: evidence.gradcam,
        duration_seconds: Math.round((Date.now() - started) / 1000),
        scope: "Grad-CAM storage, access control and doctor image display only; not the full review/publish workflow or medical accuracy.",
      }, null, 2), "utf8");
    } finally {
      await doctorContext.close();
    }
  });
}
