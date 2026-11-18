import { test as base } from "@playwright/test";

// Jenkins의 첫 탭 생성이 느려져도 실제 화면 검사 시간을 소진하지 않게 합니다.
// 기본 context를 사용해 격리·화면 크기·실패 스크린샷·trace 설정을 유지합니다.
export const test = base.extend({
  page: [async ({ context }, use) => {
    const page = await context.newPage();
    await use(page);
    // 기본 context fixture가 검사 후 페이지를 정리합니다.
  }, { timeout: process.env.CI ? 120_000 : 30_000 }],
});
