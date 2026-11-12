# 안면부 피부질환 AI 진단 보조 프로젝트

팀 프로젝트 저장소입니다. 작업별 구현은 별도 브랜치에서 검토한 뒤 통합합니다.

## YOLO11n 측면·근접 피부 사진 모델

이 브랜치는 백엔드 연동용 모델·추론 코드·평가 근거를 포함합니다. 모델 버전은 `yolo11n-side-hard-negative-20261112`입니다.

- [백엔드 연동 안내](outputs/backend_handoff/README.md)
- [응답 규격](outputs/backend_handoff/contract.json)
- [실제 응답 예시](outputs/backend_handoff/example_response.json)
- [실행 검증 기록](outputs/backend_handoff/validation.json)
- [모델 및 전달 파일 SHA256](outputs/backend_handoff/manifest.json)

Python 3.12, Windows CPU 환경에서 검증했습니다. 저장소 루트에서 실행합니다.

```sh
python -m pip install -r requirements.txt
python src/backend_inference.py --source photo.png --image-id case-image-1 --role side_closeup --output result.json
```

가중치는 `models/yolo11_detect/side_hard_negative/weights/best.pt`에 포함되어 있습니다. Python API는 `src`를 import 경로에 추가한 뒤 사용합니다.

```python
from backend_inference import DiseasePredictor

predictor = DiseasePredictor()  # 워커 시작 시 한 번 로드
result = predictor.predict("photo.png", image_id="case-image-1", role="side_closeup")
```

출력은 건선·아토피·여드름·주사·지루의 후보 점수입니다. 점수는 진단 확률이 아니며 합계 100%로 정규화하지 않습니다. 정상 확정·기타 확률·위치 상자·크롭은 제공하지 않습니다. 정면 사진은 `unsupported_input`, 전체 미검출은 `undetermined`입니다. 촬영 역할은 업로드 메타데이터로 지정해야 합니다.

관찰 이력이 있는 측면 test535장에서 질환 정답442/446(99.10%), 정상 질환 후보0/89, 질환 미검출1장입니다. 임상 성능이나 일반화 정상 오탐0%를 보장하지 않습니다. 기존 정답에서 악화된 아토피2장이 남아 있습니다. 기존 모델용 보정계수는 포함하거나 적용하지 않았습니다. HTTP 서버·대상 백엔드 환경의 동시성·응답 지연은 별도 연동 검증이 필요합니다.
