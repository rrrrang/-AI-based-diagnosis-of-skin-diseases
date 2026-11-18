<!-- 실행 방법 -->

<!-- 1. 터미널 1 — FastAPI 백엔드 -->

<!-- ① 가상환경 활성화 -->
.\.venv\Scripts\Activate.ps1

<!-- ② 의사 로그인 계정 환경변수 설정 -->
$env:SKINAI_DOCTOR_ACCOUNTS = '{
  "d1": {
    "loginId": "doctor1",
    "password": "df59a08c75c7162ad4ba79486e0ace3938aef8f6b1b984fb31c3d5ba8ccb35f8"
  },
  "d2": {
    "loginId": "doctor2",
    "password": "df59a08c75c7162ad4ba79486e0ace3938aef8f6b1b984fb31c3d5ba8ccb35f8"
  },
  "d3": {
    "loginId": "doctor3",
    "password": "df59a08c75c7162ad4ba79486e0ace3938aef8f6b1b984fb31c3d5ba8ccb35f8"
  }
}'

% ③ 백엔드 실행
python -m uvicorn main:app --reload --port 8000

% -------------------------------------------------------------------------

% 2. 터미널 2 — 환자 UI
cd frontend\patient-frontend
npm run dev

% 3. 터미널 3 — 의사 UI
cd frontend\doctor-frontend
npm run dev

% -------------------------------------------------------------------------

% 4. 터미널 4 — AI 모델 및 분석 워커

% ① 가상환경 활성화
.\.venv\Scripts\Activate.ps1

% ② PyTorch 오류 해결 여부 확인
python -c "import torch; print(torch.__version__)"

% ③ 오류가 없다면 AI 워커 실행
python -m app.worker `
  --mobilenet-root "$HOME\Desktop\skin-ai-models\mobilenet" `
  --resnet-root "$HOME\Desktop\skin-ai-models\resnet" `
  --yolo-root "$HOME\Desktop\skin-ai-models\yolo" `
  --thresholds ".\ensemble\thresholds.example.json"