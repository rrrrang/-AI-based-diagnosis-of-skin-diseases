# 백엔드 통합 MVP 병합 검토

- 대상 브랜치 `main`
- 작업 브랜치 `feature/backend-ensemble-integration`
- 검증 기준 커밋 `84fa01b`

## 변경 범위

FastAPI 접수·사진 조회·의사 소견 API, SQLite 작업 큐, YOLO11n·MobileNetV3·ResNet50 추론 워커, 환자·의사 UI의 API 연동이 함께 들어갑니다. [실행 방법](README.md)

## 확인한 결과

- 로컬 Edge에서 합성 사진 접수 → 실제 세 모델로 추론 → 담당 의사 소견 공개 → 환자 화면에서 소견 확인까지 검증했습니다.
- 백엔드 자동 테스트 7개와 앙상블 투표 규칙 테스트 1개가 통과했습니다. 중복 작업 방지, 워커 장애 복구, 사진 접근 권한, 미공개 소견 보호를 확인했습니다.
- 다른 PC에서도 동작했다는 보고를 받았습니다. 아래 체크리스트에 재현한 범위를 기록합니다.

## 병합 전 체크리스트

- [ ] 다른 PC에서 합성 사진 접수부터 환자 화면의 공개 소견 확인까지 재현한 범위를 PR에 남깁니다.
- [ ] 최신 `main`과의 충돌 여부와 자동 테스트 결과를 확인합니다.
- [ ] 팀 검토를 마친 뒤 `main`에 병합합니다.

## 검증 범위

이번 병합은 합성 사진을 사용하는 팀 시연용 MVP 기준입니다. 의사 인증은 시연용 토큰을 사용합니다. 신규 환자 사진에 대한 독립 성능 평가와 레드팀 검증은 미실시 상태입니다. [앙상블 결과](ensemble/RESULTS.md)

[PR 비교 화면](https://github.com/rrrrang/-AI-based-diagnosis-of-skin-diseases/compare/main...feature/backend-ensemble-integration?expand=1)
