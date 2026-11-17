import { test, expect, type APIRequestContext } from "@playwright/test";
import { existsSync, mkdirSync, writeFileSync } from "node:fs";
import path from "node:path";
import { DoctorWorkflowPage, PatientWorkflowPage } from "./workflow.pages";
import {
  doctorIdentityFromEnvironment, patientIdentityFromIntake, type WorkflowIdentity,
} from "../support/auth";

const API = process.env.SKINAI_E2E_API_URL || "http://127.0.0.1:18165";
const MODEL_KEYS = ["mobilenet", "resnet50", "yolo"];
const CANDIDATE_KEYS = ["psoriasis", "atopic_dermatitis", "acne", "normal", "rosacea", "seborrheic_dermatitis"];
const REVIEW_KEYS = ["diagnosis", "opinion", "visitRequired", "visitMessage"];
const PRIVATE_RESULT_KEYS = [
  "analysis", "photoIndices", "photos", "predictions", "analysisPhoto",
  "maskPhoto", "models", "modelVersions", "accessToken",
];

function requiredEnv(name: string) {
  const value = process.env[name];
  if (!value) throw new Error(`Missing required isolated-test setting: ${name}`);
  return value;
}

type Analysis = {
  decision: string;
  candidate: string | null;
  votes: Record<string, number>;
  models: Record<string, { candidate: string; score: number } | null>;
  modelVersions: Record<string, string>;
  analyzedPhotoIndex: number;
};
type CaseDetail = {
  id: string;
  aiState: string;
  reviewState: string;
  photoCount: number;
  photoIndices?: number[];
  analysis?: Analysis;
  diagnosis?: string;
  opinion?: string;
  [key: string]: unknown;
};

async function readCase(client: APIRequestContext, id: string, identity: WorkflowIdentity): Promise<CaseDetail> {
  const response = await client.get(`${API}/api/cases/${id}`, identity.requestOptions());
  expect(response.status(), "The actual backend must accept this case-specific identity.").toBe(200);
  return await response.json() as CaseDetail;
}

function assertPatientProjection(detail: CaseDetail, published: boolean) {
  // Assert the raw server response, not only what React chooses to render.
  for (const key of PRIVATE_RESULT_KEYS) {
    expect(Object.prototype.hasOwnProperty.call(detail, key), `Patient response must omit ${key}`).toBe(false);
  }
  if (!published) {
    for (const key of REVIEW_KEYS) {
      expect(Object.prototype.hasOwnProperty.call(detail, key), `Draft must omit ${key}`).toBe(false);
    }
  }
}

for (const photoCount of [2, 3] as const) {
  test(`실제 UI·3모델 연결: 사진 ${photoCount}장 접수 → 의사 확정 → 환자 결과`, async ({ page, browser }) => {
    const sample = requiredEnv("SKINAI_E2E_SAMPLE");
    const doctorIdentity = doctorIdentityFromEnvironment();
    const output = requiredEnv("SKINAI_E2E_OUTPUT");
    expect(existsSync(sample), "A prepared local, non-personal close-up fixture is required.").toBe(true);
    const doctorContext = await browser.newContext({ viewport: { width: 1440, height: 1080 } });
    const doctorPage = await doctorContext.newPage();
    const patient = new PatientWorkflowPage(page);
    const doctor = new DoctorWorkflowPage(doctorPage);
    const unique = Date.now().toString(36);
    const patientName = `CI연결${photoCount}-${unique}`;
    const diagnosis = `CI 확인용 결과 ${photoCount}-${unique}`;
    const opinion = "사진 전송과 의사 확정 후 공개를 확인한 자동검사 문구입니다. 실제 의료 소견이 아닙니다.";
    const started = Date.now();

    try {
      const bookingDate = await patient.reserveDoctor();
      await patient.photosAndSymptoms(sample, photoCount);
      await patient.fillPatient(patientName);

      const intakeResponse = page.waitForResponse((r) =>
        new URL(r.url()).pathname === "/api/cases" && r.request().method() === "POST");
      const queueResponse = page.waitForResponse((r) =>
        /^\/api\/cases\/[^/]+\/analyze$/.test(new URL(r.url()).pathname) &&
        r.request().method() === "POST");
      await page.getByRole("button", { name: "AI 분석 요청", exact: true }).click();
      const intake = await intakeResponse;
      expect(intake.status(), "UI must create a real backend case; demo storage is not accepted.").toBe(201);
      const patientIdentity = patientIdentityFromIntake(await intake.json());
      const caseId = patientIdentity.caseId;
      const queued = await queueResponse;
      expect(new URL(queued.url()).pathname).toBe(`/api/cases/${caseId}/analyze`);
      expect(queued.status(), "The actual model worker must accept the request.").toBe(202);
      await expect(page).toHaveURL(/#\/patient\/result$/);
      await expect(page.getByRole("heading", { name: "AI 피부 분석 결과" })).toBeVisible();

      const beforeAnalysis = await readCase(page.request, caseId, patientIdentity);
      expect(beforeAnalysis.photoCount).toBe(photoCount);
      assertPatientProjection(beforeAnalysis, false);
      await expect(page.getByRole("heading", { name: "최종 모의 검토 결과" })).toHaveCount(0);

      await doctor.connect(doctorIdentity, bookingDate, patientName);
      let complete: CaseDetail | undefined;
      await expect.poll(async () => {
        complete = await readCase(doctorPage.request, caseId, doctorIdentity);
        return complete.aiState;
      }, { message: "The real three-model worker must finish the submitted close-up.",
        timeout: 240_000, intervals: [1000, 3000, 5000] }).toBe("완료");
      expect(complete).toBeDefined();
      const analysis = complete!.analysis!;
      expect(analysis, "Doctor-only analysis must be provided by the worker.").toBeTruthy();
      expect(Object.keys(analysis.models).sort()).toEqual([...MODEL_KEYS].sort());
      expect(Object.keys(analysis.modelVersions).sort()).toEqual([...MODEL_KEYS].sort());
      expect(analysis.analyzedPhotoIndex, "Slot 1 is analyzed; the front is contextual only.").toBe(1);
      for (const model of MODEL_KEYS) {
        expect(analysis.modelVersions[model]).toMatch(/^[a-f0-9]{64}$/);
        const prediction = analysis.models[model];
        if (model !== "yolo") {
          expect(prediction, `${model} must return a classifier prediction.`).not.toBeNull();
        }
        if (prediction !== null) {
          expect(CANDIDATE_KEYS).toContain(prediction.candidate);
          if (model === "yolo") expect(prediction.candidate).not.toBe("normal");
          expect(Number.isFinite(prediction.score)).toBe(true);
          expect(prediction.score).toBeGreaterThanOrEqual(0);
          expect(prediction.score).toBeLessThanOrEqual(1);
        }
      }
      expect(["majority", "single_qualified", "normal_consensus", "deferred", "undetermined"])
        .toContain(analysis.decision);
      expect(complete!.photoIndices).toEqual(photoCount === 3 ? [0, 1, 2] : [0, 1]);

      // Refresh the actual doctor screen, then verify that it obtains authorized photos.
      const listResponse = doctorPage.waitForResponse((r) =>
        new URL(r.url()).pathname === "/api/cases" && r.request().method() === "GET");
      await doctorPage.getByRole("button", { name: "예약 정보 새로고침", exact: true }).click();
      expect((await listResponse).status()).toBe(200);
      const photoResponses = Array.from({ length: photoCount }, (_, index) =>
        doctorPage.waitForResponse((r) =>
          new URL(r.url()).pathname === `/api/cases/${caseId}/photos/${index}` &&
          r.request().method() === "GET"));
      await doctor.openPatient(patientName);
      for (const response of await Promise.all(photoResponses)) expect(response.status()).toBe(200);
      for (const label of photoCount === 3 ? ["정면", "증상 부위 1", "증상 부위 2"] : ["정면", "증상 부위 1"]) {
        const photo = doctorPage.getByRole("img", { name: label, exact: true });
        await expect(photo).toBeVisible();
        await expect.poll(() => photo.evaluate((img) => (img as HTMLImageElement).naturalWidth)).toBeGreaterThan(0);
      }
      await expect(doctorPage.getByRole("img", { name: "AI 분석 원본", exact: true })).toBeVisible();
      await expect(doctorPage.getByRole("button", { name: "시연용 예측 그래프 표시" })).toHaveCount(0);
      const decisionText = analysis.decision === "deferred" ? "판단 보류" :
        analysis.decision === "undetermined" ? "판단 불가" : `검토 후보 · ${analysis.candidate}`;
      await expect(doctorPage.getByText(decisionText, { exact: true })).toBeVisible();

      await doctor.fillReview(diagnosis, opinion);
      await doctor.saveDraft(caseId);
      const draftDoctor = await readCase(doctorPage.request, caseId, doctorIdentity);
      expect(draftDoctor.reviewState).toBe("임시 저장");
      const beforePublish = await readCase(page.request, caseId, patientIdentity);
      expect(beforePublish.reviewState).toBe("검토 대기");
      assertPatientProjection(beforePublish, false);
      await patient.refreshResults(caseId);
      await expect(page.getByRole("heading", { name: "최종 모의 검토 결과" })).toHaveCount(0);
      await expect(page.getByText(diagnosis, { exact: false })).toHaveCount(0);

      await doctor.publish(caseId);
      const finalPatient = await readCase(page.request, caseId, patientIdentity);
      expect(finalPatient.reviewState).toBe("결과 전달 완료");
      expect(finalPatient.diagnosis).toBe(diagnosis);
      expect(finalPatient.opinion).toBe(opinion);
      assertPatientProjection(finalPatient, true);
      await patient.refreshResults(caseId);
      await expect(page.getByRole("heading", { name: "최종 모의 검토 결과" })).toBeVisible();
      await expect(page.getByText(`검토 내용: ${diagnosis}`, { exact: true })).toBeVisible();
      await expect(page.getByText(`의사 소견: ${opinion}`, { exact: true })).toBeVisible();
      await expect(page.locator("img")).toHaveCount(0);

      mkdirSync(output, { recursive: true });
      // Deliberately omit tokens, photo paths, image data, and full clinical payloads.
      writeFileSync(path.join(output, `workflow-${photoCount}-photos.json`), JSON.stringify({
        status: "passed",
        case_id: caseId,
        photo_count: photoCount,
        intake_http: 201,
        analysis_request_http: 202,
        analyzed_photo_index: analysis.analyzedPhotoIndex,
        model_keys: MODEL_KEYS,
        model_versions: analysis.modelVersions,
        actual_model_decision: analysis.decision,
        checked: {
          actual_patient_and_doctor_ui: true,
          three_real_model_results: true,
          doctor_photo_access: true,
          draft_hidden_from_patient_api_and_ui: true,
          confirmed_text_visible_to_patient: true,
          patient_response_excludes_photos_and_ai: true,
          patient_page_contains_no_images: true,
        },
        duration_seconds: Math.round((Date.now() - started) / 1000),
        scope: "Integration only. Synthetic front fixture, prepared close-up; not face detection or medical accuracy.",
        normal_and_hold_branches: "Only the sample's actual decision was exercised; other outcomes are not claimed.",
      }, null, 2), "utf8");
    } finally {
      await doctorContext.close();
    }
  });
}
