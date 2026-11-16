import { expect, type Page } from "@playwright/test";
import { Buffer } from "node:buffer";

// Synthetic, non-personal front fixture; the real worker analyzes close-up slot 1.
// This checks transmission and visibility, not face quality or diagnosis accuracy.
const FRONT_FIXTURE = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAgAAAAICAIAAABLbSncAAAAD0lEQVR4nGNowAEYhpYEAILzYAGc7g8kAAAAAElFTkSuQmCC",
  "base64",
);

export class PatientWorkflowPage {
  constructor(readonly page: Page) {}

  async reserveDoctor(): Promise<string> {
    await this.page.goto("/#/patient/reservation");
    await this.page.getByRole("button", { name: /김서연/ }).click();
    await this.page.getByRole("button", { name: "날짜·시간 선택" }).click();
    // Calendar has no date labels yet. Keep these two layout selectors here only.
    for (let month = 0; month < 3; month += 1) {
      const available = this.page.locator(".res-dates button:not([disabled])");
      if (await available.count()) {
        await available.first().click();
        break;
      }
      await this.page.getByRole("button", { name: "다음 달", exact: true }).click();
    }
    await this.page.locator(".res-time-grid button:not([disabled])").first().click();
    const date = (await this.page.locator(".res-booking-detail strong").first().innerText()).trim();
    expect(date).toMatch(/^\d{4}-\d{2}-\d{2}$/);
    await this.page.getByRole("button", { name: "예약 확정", exact: true }).click();
    await expect(this.page.getByRole("heading", { name: "피부 사진 등록" })).toBeVisible();
    return date;
  }

  async photosAndSymptoms(sample: string, count: 2 | 3) {
    const front = this.page.waitForEvent("filechooser");
    await this.page.getByRole("button", { name: "정면 사진 추가", exact: true }).click();
    await (await front).setFiles({
      name: "synthetic-front.png", mimeType: "image/png", buffer: FRONT_FIXTURE,
    });
    await expect(this.page.getByRole("button", { name: "정면 사진 삭제" })).toBeVisible();
    for (const slot of count === 3 ? ["부위 1", "부위 2"] : ["부위 1"]) {
      const chooser = this.page.waitForEvent("filechooser");
      await this.page.getByRole("button", { name: slot + " 사진 추가", exact: true }).click();
      await (await chooser).setFiles(sample);
      await expect(this.page.getByRole("button", { name: slot + " 사진 삭제" })).toBeVisible();
    }
    await this.page.getByRole("button", { name: "가려움", exact: true }).click();
    await this.page.getByLabel("증상 발생 시점").selectOption({ label: "1~3일" });
    await this.page.getByRole("button", { name: "다음", exact: true }).click();
    await expect(this.page.getByRole("heading", { name: "환자 정보 입력" })).toBeVisible();
  }

  async fillPatient(name: string) {
    await this.page.getByLabel("환자 이름").fill(name);
    await this.page.getByLabel("환자 나이").fill("30");
    await this.page.getByRole("button", { name: "선택 안 함", exact: true }).click();
    await this.page.getByPlaceholder("증상이 나타난 부위, 시작 시점, 불편한 점을 적어주세요.")
      .fill("CI 통합검사용 가상 접수입니다. 실제 환자 문진이 아닙니다.");
    await this.page.getByRole("checkbox").check();
  }

  async refreshResults(caseId: string) {
    const response = this.page.waitForResponse((r) =>
      new URL(r.url()).pathname === `/api/cases/${caseId}` && r.request().method() === "GET");
    const refresh = this.page.getByRole("button", { name: "검토 상태 새로고침", exact: true });
    await refresh.click();
    const refreshed = await response;
    expect(refreshed.status()).toBe(200);
    await refreshed.finished();
    await expect(refresh).toBeEnabled();
  }
}

export class DoctorWorkflowPage {
  constructor(readonly page: Page) {}

  async connect(token: string, date: string, patientName: string) {
    const doctorUrl = process.env.SKINAI_E2E_DOCTOR_URL || "http://127.0.0.1:18167";
    await this.page.goto(`${doctorUrl}/#/doctor`);
    await this.page.getByLabel("시연용 의사 토큰").fill(token);
    const response = this.page.waitForResponse((r) =>
      new URL(r.url()).pathname === "/api/cases" && r.request().method() === "GET");
    await this.page.getByRole("button", { name: "접수 목록 연결", exact: true }).click();
    expect((await response).status()).toBe(200);
    await this.page.getByLabel("예약 날짜", { exact: true }).fill(date);
    await this.page.getByPlaceholder("환자명 검색").fill(patientName);
  }

  async openPatient(patientName: string) {
    await this.page.getByRole("row").filter({ hasText: patientName })
      .getByRole("button", { name: "검토하기", exact: true }).click();
  }

  async fillReview(diagnosis: string, opinion: string) {
    await this.page.getByPlaceholder("질환 후보 또는 판단 보류").fill(diagnosis);
    await this.page.getByPlaceholder("환자 사진과 증상, AI 결과를 종합해 소견을 작성하세요.").fill(opinion);
  }

  async saveDraft(caseId: string) {
    const response = this.page.waitForResponse((r) =>
      new URL(r.url()).pathname === `/api/cases/${caseId}/review` && r.request().method() === "PATCH");
    await this.page.getByRole("button", { name: "임시 저장", exact: true }).click();
    expect((await response).status()).toBe(200);
  }

  async publish(caseId: string) {
    await this.page.getByRole("button", { name: "최종 결과 확정", exact: true }).click();
    const dialog = this.page.getByRole("dialog");
    await expect(dialog).toBeVisible();
    const response = this.page.waitForResponse((r) =>
      new URL(r.url()).pathname === `/api/cases/${caseId}/review` && r.request().method() === "PATCH");
    await dialog.getByRole("button", { name: "확정", exact: true }).click();
    expect((await response).status()).toBe(200);
    await expect(dialog).not.toBeVisible();
  }
}