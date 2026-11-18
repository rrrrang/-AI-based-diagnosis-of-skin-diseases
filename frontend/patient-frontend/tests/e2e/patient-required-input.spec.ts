import { test } from "@playwright/test";
import { PatientUploadPage } from "../pages/patient-upload.page";

// 필수값을 하나씩 빠뜨렸을 때 나와야 하는 안내
const missingCases = [
  {
    name: "정면 사진이 없으면 다음 단계로 넘어가지 않는다",
    missing: "front",
    message: "얼굴 전체가 보이는 정면 사진을 먼저 등록해 주세요.",
  },
  {
    name: "부위 사진이 없으면 다음 단계로 넘어가지 않는다",
    missing: "lesion",
    message: "피부질환이 발생한 부위 사진을 최소 1장 등록해 주세요.",
  },
  {
    name: "증상을 선택하지 않으면 다음 단계로 넘어가지 않는다",
    missing: "symptom",
    message: "현재 피부 증상을 하나 이상 선택해 주세요.",
  },
  {
    name: "발생 시점을 선택하지 않으면 다음 단계로 넘어가지 않는다",
    missing: "duration",
    message: "증상 발생 시점을 선택해 주세요.",
  },
] as const;

test.describe("환자 사진·증상 필수 입력 검사", () => {
  // 위에 작성한 4가지 누락 사례를 각각 검사
  for (const scenario of missingCases) {
    test(scenario.name, async ({ page }) => {
      const upload = new PatientUploadPage(page);

      await upload.open();

      // 검사 대상인 한 항목만 비우고 나머지는 모두 입력
      if (scenario.missing !== "front") {
        await upload.addFrontPhoto();
      }

      if (scenario.missing !== "lesion") {
        await upload.addLesionPhoto();
      }

      if (scenario.missing !== "symptom") {
        await upload.selectSymptom();
      }

      if (scenario.missing !== "duration") {
        await upload.selectDuration();
      }

      await upload.clickNext();

      // 해당 항목의 오류 안내와 현재 화면 유지를 확인
      await upload.expectBlocked(scenario.message);
    });
  }

  // 정상 입력도 확인해야 항상 막히는 화면을 걸러낼 수 있음
  test("필수값을 모두 입력하면 환자 정보 화면으로 이동한다", async ({ page }) => {
    const upload = new PatientUploadPage(page);

    await upload.open();
    await upload.addFrontPhoto();
    await upload.addLesionPhoto();
    await upload.selectSymptom();
    await upload.selectDuration();

    await upload.clickNext();

    await upload.expectPatientInfo();
  });
});