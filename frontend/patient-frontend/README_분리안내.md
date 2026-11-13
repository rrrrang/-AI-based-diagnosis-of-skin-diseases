# 환자 전용 프론트엔드

원본: frontend(20261111-064802).zip

- 원래 페이지 JSX / UI CSS / 데이터 서비스 코드는 유지했습니다.
- 수정 파일: `src/App.tsx`, `src/components/MainHeader.tsx`, `vite.config.ts`, 패키지 이름.
- 실행: `npm install` 다음 `npm run dev`
- 로컬 주소: http://localhost:5173/
- HashRouter를 그대로 유지해 `#/patient` 또는 `#/doctor` 경로를 사용합니다.
- 중앙 서버 연결 전에는 **환자·의사 사이트 사이에 IndexedDB/localStorage 데이터가 공유되지 않습니다.**
- 따라서 지금 단계에서는 두 개의 독립 UI가 표시되는지만 확인하세요. 실제 접수 공유/AI 분석은 백엔드 API 연동이 필요합니다.
- 시연용 데이터만 사용하고 실환자 정보는 입력하지 마세요.
