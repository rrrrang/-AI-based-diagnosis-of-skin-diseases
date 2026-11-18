import { defineConfig } from "@playwright/test";

export default defineConfig({
  // 실제 검사 파일을 둘 폴더
  testDir: "./tests/e2e",

  // 한 번에 하나씩 검사
  workers: 1,
  retries: 0,
  forbidOnly: true,

  // 검사 하나당 최대 대기 시간
  timeout: 30_000,

  // 터미널에 검사 결과 표시
  reporter: "list",

  // 실패 기록 저장 위치
  outputDir: "./test-results",

  use: {
    browserName: "chromium",
    baseURL: "http://127.0.0.1:18140",
    viewport: { width: 390, height: 844 },

    // 실패한 경우 확인할 화면과 실행 기록
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
  },

  webServer: {
    // 환자 UI를 빌드한 뒤 검사용 서버 실행
    command:
      "npm run build && npm run preview -- --host 127.0.0.1 --port 18140 --strictPort",

    url: "http://127.0.0.1:18140",
    timeout: 180_000,

    // 다른 서버를 잘못 검사하지 않도록 기존 서버 재사용 금지
    reuseExistingServer: false,
  },
});