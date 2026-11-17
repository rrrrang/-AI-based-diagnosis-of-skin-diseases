# 안면부 피부질환 AI 진단 보조 프로젝트 — YOLO11n

이 브랜치는 **정상 포함6클래스 YOLO11n 모델 전달 패키지**입니다. 기존5클래스 파일 구성을 교체했으며 이전 버전은 커밋`1ae1287`에서 확인할 수 있습니다. 강제 푸시나 과거 이력 삭제는 하지 않습니다.

- 모델 버전: `yolo11n-side-six-class-20261117`
- 가중치: `models/yolo11_detect/side_six_class_augmented/weights/best.pt`
- SHA256: `e792fb2374a6024f49249a40a9f2807282ef8d1bad9c3ec5c2f48055d03ed800`
- 클래스: **0건선 / 1아토피 / 2여드름 / 3정상 / 4주사 / 5지루**
- 응답 규격: **2.0**, Python API 호출 이름은 `DiseasePredictor` 유지

## 실행

Python3.12 Windows CPU 환경에서 확인했습니다. 저장소 루트에서 실행합니다.

```sh
python -m pip install -r requirements.txt
python src/backend_inference.py --source photo.png --image-id case-image-1 --role side_closeup --output result.json
python -m pytest src/test_backend_inference.py -q
```

```python
# src를 import 경로에 추가한 후 사용
from backend_inference import DiseasePredictor
predictor = DiseasePredictor()  # 워커당 한 번 로드, 같은 인스턴스의 호출은 직렬화
result = predictor.predict("photo.png", image_id="case-image-1", role="side_closeup")
```

원본 사진을 전달하세요. 공통224×224 축소나 ImageNet 정규화를 먼저 적용하지 않습니다. 모델 내부에서 방향/RGB/640입력을 처리합니다. conf0.25/NMS0.7/FP32/rectFalse/추가증강0/CPU로 고정합니다.

## 백엔드 통합 전 필수 변경

기존 backend가 이전 경로를 지정하면 SHA 검사에서 거절됩니다. YOLO 모델 경로와 배포 소스커밋·파일 SHA를 새 버전으로 갱신해야 합니다. `ensemble/policy.py`의 YOLO 정상후보 거절 규칙도 팀의6클래스 정상 투표/합의/보류 정책과 테스트로 수정해야 합니다. 기존3주사는새4, 기존4지루는새5이며 새3은정상입니다. 숫자ID보다 공통코드로 연결하세요.

이 브랜치는 모델·추론 규격만 제공합니다. **main의 앙상블/배포 코드를 수정하거나 서비스를 배포하지 않습니다.** 백엔드 담당자는 `outputs/backend_handoff/README.md`의 이전 항목을 먼저 확인하세요.

## 출력과 성능

정상 포함6개 후보 점수를 독립적으로 반환합니다. 정상 후보도 검토용이며 확정 진단이 아닙니다. 점수는 진단확률이 아니고 합계100%로 정규화하지 않습니다. 미검출은null, 전체 미검출은undetermined, 정면은unsupported_input입니다. 입력 역할 자동 판별·상자 표시·크롭·기타 확률은 제공하지 않습니다.

고정 측면test535장: 질환442/446(99.10%), 정상top1 86/89(96.63%), 전체528/535(98.69%). 정상top1질환오류3장과 정상에서질환후보가하나라도발생한5장을 구분합니다. 질환미검출과질환→정상은0장이지만, 기존 관찰test·환자독립성미확인이므로 독립 임상 성능이나 모든 외부사진 성능을 보장하지 않습니다. 외부 여드름 사진을 건선으로 예측한 사례도 있어 실제 촬영조건 평가가 추가로 필요합니다.

## 문서와 증거

- [입력·출력·이전 안내](outputs/backend_handoff/README.md)
- [응답 규격](outputs/backend_handoff/contract.json)
- [질환 후보 실제 응답](outputs/backend_handoff/example_response.json)
- [정상 후보 실제 응답](outputs/backend_handoff/example_normal_response.json)
- [실행 검증](outputs/backend_handoff/validation.json)
- [파일별 SHA](outputs/backend_handoff/manifest.json)
- [validation](outputs/detection_evaluation/side_six_class_validation/summary.json)
- [측면 test](outputs/detection_evaluation/side_six_class_test/summary.json)

원천사진·학습데이터·이전가중치·보정계수·대용량ZIP은 포함하지 않습니다. 가중치는약5.5MB 실제파일입니다. 이전버전복구는 별도폴더에서커밋1ae1287을체크아웃하면되며, main 병합과실제배포는팀통합검증후수행합니다.
