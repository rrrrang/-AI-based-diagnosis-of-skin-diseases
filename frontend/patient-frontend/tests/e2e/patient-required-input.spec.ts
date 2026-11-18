import { test } from "../support/ui-test";
import { Buffer } from "node:buffer";
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
    message: "부위 1에 피부질환이 잘 보이는 근접 사진을 등록해 주세요.",
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

  const rejectedFiles = [
    {
      name: "백엔드가 받지 않는 WebP 사진을 거절한다",
      filename: "unsupported.webp",
      mimeType: "image/webp",
      byteLength: 32,
      message: "JPG, PNG 이미지만 등록할 수 있습니다.",
    },
    {
      name: "8MiB보다 1바이트 큰 사진을 거절한다",
      filename: "oversized.png",
      mimeType: "image/png",
      byteLength: 8 * 1024 * 1024 + 1,
      message: "사진 한 장의 크기는 8MB(8,388,608바이트) 이하여야 합니다.",
    },
  ];

  for (const scenario of rejectedFiles) {
    test(scenario.name, async ({ page }) => {
      const upload = new PatientUploadPage(page);
      await upload.open();
      await upload.addFrontPhoto();
      await upload.selectSymptom();
      await upload.selectDuration();
      // 형식·크기 검사는 파일 내용 해석보다 앞에서 차단해야 합니다.
      await upload.selectPhotoFile("부위 1", {
        name: scenario.filename,
        mimeType: scenario.mimeType,
        buffer: Buffer.alloc(scenario.byteLength),
      });
      await upload.expectBlocked(scenario.message);
      await upload.expectPhotoMissing("부위 1");
      await upload.clickNext();
      await upload.expectBlocked("부위 1에 피부질환이 잘 보이는 근접 사진을 등록해 주세요.");
      // 잘못된 선택을 거절한 뒤에도 정상 PNG를 다시 선택할 수 있어야 합니다.
      await upload.addLesionPhoto();
      await upload.clickNext();
      await upload.expectPatientInfo();
      await upload.expectPhotoCount(2);
    });
  }

  // 정상 입력도 확인해야 항상 막히는 화면을 걸러낼 수 있음
  test("정면과 근접 사진 2장만 입력해도 환자 정보 화면으로 이동한다", async ({ page }) => {
    const upload = new PatientUploadPage(page);

    await upload.open();
    await upload.addFrontPhoto();
    await upload.addLesionPhoto();
    await upload.selectSymptom();
    await upload.selectDuration();

    await upload.clickNext();

    await upload.expectPatientInfo();
    await upload.expectPhotoCount(2);
  });

  test("선택 근접 사진까지 3장을 등록하면 모두 다음 화면에 전달된다", async ({ page }) => {
    const upload = new PatientUploadPage(page);
    await upload.open();
    await upload.addFrontPhoto();
    await upload.addLesionPhoto();
    await upload.addExtraLesionPhoto();
    await upload.selectSymptom();
    await upload.selectDuration();
    await upload.clickNext();
    await upload.expectPatientInfo();
    await upload.expectPhotoCount(3);
    await upload.returnToUpload();
    await upload.removePhoto("부위 2");
    await upload.clickNext();
    await upload.expectPatientInfo();
    await upload.expectPhotoCount(2);
  });

  test("선택 사진만으로 필수 근접 사진을 대신할 수 없다", async ({ page }) => {
    const upload = new PatientUploadPage(page);
    await upload.open();
    await upload.addFrontPhoto();
    await upload.addExtraLesionPhoto();
    await upload.selectSymptom();
    await upload.selectDuration();
    await upload.clickNext();
    await upload.expectBlocked("부위 1에 피부질환이 잘 보이는 근접 사진을 등록해 주세요.");
  });

  test("3장 중 필수 근접 사진을 지우면 진행이 차단되고 다시 넣으면 복구된다", async ({ page }) => {
    const upload = new PatientUploadPage(page);
    await upload.open();
    await upload.addFrontPhoto();
    await upload.addLesionPhoto();
    await upload.addExtraLesionPhoto();
    await upload.selectSymptom();
    await upload.selectDuration();
    await upload.removePhoto("부위 1");
    await upload.clickNext();
    await upload.expectBlocked("부위 1에 피부질환이 잘 보이는 근접 사진을 등록해 주세요.");
    await upload.addLesionPhoto();
    await upload.clickNext();
    await upload.expectPatientInfo();
    await upload.expectPhotoCount(3);
  });
});
