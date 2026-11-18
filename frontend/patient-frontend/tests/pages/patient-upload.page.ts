import { expect, type Page } from "@playwright/test";
import { Buffer } from "node:buffer";

// 파일 등록 흐름만 확인하는 작은 회색 PNG입니다.
// 실제 환자 사진이나 AI 분석용 사진이 아닙니다.
const TEST_IMAGE = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAgAAAAICAIAAABLbSncAAAAD0lEQVR4nGNowAEYhpYEAILzYAGc7g8kAAAAAElFTkSuQmCC",
  "base64"
);

export class PatientUploadPage {
  readonly page: Page;

  constructor(page: Page) {
    this.page = page;
  }

  // 사진·증상 입력 화면 열기
  async open() {
    await this.page.goto("/#/patient/upload");

    await expect(
      this.page.getByRole("heading", {
        name: "피부 사진 등록",
        exact: true,
      })
    ).toBeVisible();
  }

  // 지정한 사진 칸에 검사 이미지를 등록하는 공통 기능
  private async addPhoto(slot: "정면" | "부위 1") {
    const chooserPromise = this.page.waitForEvent("filechooser");

    await this.page.getByRole("button", {
      name: `${slot} 사진 추가`,
      exact: true,
    }).click();

    const chooser = await chooserPromise;

    await chooser.setFiles({
      name: slot === "정면" ? "front-test.png" : "lesion-test.png",
      mimeType: "image/png",
      buffer: TEST_IMAGE,
    });

    // 등록 후 해당 사진의 삭제 버튼이 나타나는지 확인
    await expect(
      this.page.getByRole("button", {
        name: `${slot} 사진 삭제`,
        exact: true,
      })
    ).toBeVisible();
  }

  // 정면 사진 등록
  async addFrontPhoto() {
    await this.addPhoto("정면");
  }

  // 부위 사진 등록
  async addLesionPhoto() {
    await this.addPhoto("부위 1");
  }

  // 증상 선택
  async selectSymptom(symptom = "가려움") {
    const button = this.page.getByRole("button", {
      name: symptom,
      exact: true,
    });

    await button.click();
    await expect(button).toHaveAttribute("aria-pressed", "true");
  }

  // 증상 발생 시점 선택
  async selectDuration(duration = "1~3일") {
    const select = this.page.getByLabel("증상 발생 시점", {
      exact: true,
    });

    await select.selectOption({ label: duration });
    await expect(select).toHaveValue(duration);
  }

  // 다음 버튼 누르기
  async clickNext() {
    await this.page.getByRole("button", {
      name: "다음",
      exact: true,
    }).click();
  }

  // 오류 안내가 나오고 현재 화면에 머무는지 확인
  async expectBlocked(message: string) {
    await expect(
      this.page.getByRole("alert")
    ).toHaveText(message);

    await expect(this.page).toHaveURL(/\/#\/patient\/upload$/);

    await expect(
      this.page.getByRole("heading", {
        name: "피부 사진 등록",
        exact: true,
      })
    ).toBeVisible();
  }

  // 필수값을 모두 입력하면 환자 정보 화면으로 이동하는지 확인
  async expectPatientInfo() {
    await expect(this.page).toHaveURL(/\/#\/patient\/info$/);

    await expect(
      this.page.getByRole("heading", {
        name: "환자 정보 입력",
        exact: true,
      })
    ).toBeVisible();
  }
}