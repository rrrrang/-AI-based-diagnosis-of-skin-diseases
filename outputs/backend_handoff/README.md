# YOLO11n 정상 포함 6클래스 백엔드 전달

전달 모델은 `yolo11n-side-six-class-20261117`입니다. 가중치는 `models/yolo11_detect/side_six_class_augmented/weights/best.pt`, SHA256은 `e792fb2374a6024f49249a40a9f2807282ef8d1bad9c3ec5c2f48055d03ed800`입니다.

## 입력과 실행

Python3.12 Windows CPU 환경에서 검증합니다. 설치와 실행은 저장소 또는 ZIP 추출 루트에서 수행합니다.

```sh
python -m pip install -r requirements.txt
python src/backend_inference.py --source photo.png --image-id case-image-1 --role side_closeup --output result.json
python -m pytest src/test_backend_inference.py -q
```

Python API는 기존 호출 이름을 유지합니다. `src`를 import 경로에 추가한 뒤 사용합니다.

```python
from backend_inference import DiseasePredictor
predictor = DiseasePredictor()  # 워커 시작 시 한 번 생성
result = predictor.predict("photo.png", image_id="case-image-1", role="side_closeup")
```

image는 PIL 이미지 또는 로컬 파일 경로입니다. 원본 사진을 각 모델에 전달하고, 공통224×224 축소본을 먼저 만들지 마세요. 이 모델은 EXIF 방향 보정·RGB 변환 후 Ultralytics 내부에서 비율 유지 resize/padding과0~1 정규화를 적용합니다. full 입력, imgsz640, confidence0.25, NMS IoU0.7, rect=False, FP32, max_det300, 추가증강 없음, CPU 고정입니다. 외부에서 ImageNet 정규화를 중복 적용하지 않습니다.

지원 입력은 학습·측면 평가와 유사한 측면/근접 피부 사진입니다. 정면 전체 사진은 role=`front`로 지정하며 `unsupported_input`을 반환합니다. 촬영 역할을 자동 판별하지 않으므로 업로드 메타데이터로 구분해야 합니다. 클래스 밖의 질환·외부 사진·휴대폰 실사진 일반화 성능은 보장하지 않습니다.

워커별 인스턴스를 두고 같은 인스턴스의 동시 호출은 직렬화하세요. 잘못된 이미지와 가중치는 ValueError/파일 접근 예외로 전달되므로 HTTP 계층에서 입력 오류와 서버 오류를 매핑해야 합니다. 이 패키지는 Python API/CLI이며 HTTP 서버·대상 백엔드 배포·동시성·지연은 별도 검증 대상입니다.

## 응답 규격 2.0

| ID | 공통 코드 | 표시 |
|---|---|---|
| 0 | psoriasis | 건선 |
| 1 | atopic_dermatitis | 아토피 |
| 2 | acne | 여드름 |
| 3 | normal | 정상 |
| 4 | rosacea | 주사 |
| 5 | seborrheic_dermatitis | 지루 |

`disease_scores`는 정상 포함6개 항목을 고정 반환합니다. score는 유지된 상자 중 클래스별 최고 탐지 confidence(0~1) 또는null입니다. 미검출 항목은null이며0% 확률을 뜻하지 않습니다. 하나라도 검출되면 `candidates_for_review`, 전체 미검출이면 `undetermined`입니다. 정상만 검출돼도 정상 확정 대신 검토용 후보로 반환합니다. `top_candidate`는 최고 점수 후보이며 동점이면 작은class_id를 선택합니다.

점수×100을 'AI 탐지 점수'로 표시할 수 있지만 합계100%로 정규화하거나 발병/진단 확률로 해석하면 안 됩니다. 정상과 다른 질환이 동시에 검출될 수 있어 모든 점수를 유지합니다. `normal_confirmed=False`는 의학적 정상 확정을 하지 않는다는 뜻이며 정상 후보가 없다는 뜻이 아닙니다. 위치 좌표·크롭·정면 위치 연결·기타 확률은 제공하지 않습니다. 기존 보정계수는 적용/동봉하지 않습니다.

규격은 contract.json, 실제 질환 후보 예시는 example_response.json, 정상 후보 예시는 example_normal_response.json에 있습니다. validation.json에는 실제검증사진·추출CLI·회귀검사와 의존성 버전을 기록합니다.

## 5클래스에서 이전할 때 백엔드팀이 함께 바꿀 항목

이번 변경은 schema1.0→2.0입니다. 기존3주사는 새4주사, 기존4지루는 새5지루로 바뀌고 정상은 새3입니다. 숫자ID 대신 공통코드로 집계하세요. 이전5클래스 가중치를 새adapter에 넣으면 SHA/클래스 검증에서 거부됩니다.

확인한 main의 연동 상태는 다음과 같습니다. 이 전달 브랜치에서는 main의 앙상블/배포 정책을 직접 변경하지 않습니다.

- `ensemble/__main__.py`: YOLO 가중치 경로를 `models/yolo11_detect/side_six_class_augmented/weights/best.pt`로 변경하거나 `DiseasePredictor()`의 새 기본 경로를 사용해야 합니다.
- `ensemble/policy.py`: 현재 YOLO의normal 후보를 오류로 거절합니다. 팀의6클래스 정책에 맞춰 normal 투표·정상 합의·보류 조건과 관련 테스트를 갱신해야 합니다. 이 모델이 임의로 normal→미검출로 숨기지는 않습니다.
- `ci/release/backend/model-lock.json` 및 관련가드: YOLO 소스커밋·파일경로·SHA를 이번 브랜치의 새 커밋으로 갱신해야 합니다. 고정이전커밋1ae1287을 계속 사용하면 새 모델이 반영되지 않습니다.
- 기존 YOLO 투표 점수 기준은 새모델에 자동 재사용하지 말고, 세모델 공통validation에서 검증하세요. 모델별 원점수/정상confidence를 바로 평균하거나 정상=1-최고질환점수로 만들지 않습니다.

업로드/모델브랜치 갱신과 실제 서비스 배포는 별개입니다. 팀의 정상정책 수정과 공통 입력 추론·오류·미검출·동시성 검증 후 통합합니다. main 병합/강제푸시/배포는 이 작업에 포함하지 않습니다.

## 성능과 한계

학습8epoch, best1epoch입니다. validation은 질환508/514(98.83%), 정상top1 104/105, 정상에서다른질환후보하나라도발생11/105입니다.

측면test535장에서 질환442/446(99.10%), 정상top1 86/89(96.63%), 전체528/535(98.69%), macroF1=0.9869입니다. 정상top1질환오류3/89, 정상질환후보발생5/89, 질환미검출0/446, 질환→정상0/446입니다. 정상top1 정답이어도 다른질환후보가 함께 나올 수 있어3건과5건은 다른 지표입니다. 이전5클래스도 질환442/446이었고 새모델은 정상 후보를 추가했으므로 모든 지표가 개선됐다고 쓰지 않습니다.

test mAP50=99.03%, mAP50-95=87.58%는 넓은 제공자 피부 상자 기준이며 정확한 국소 병변 경계 성능이 아닙니다. 기존 관찰test·환자독립성미확인·validation 선택 이력을 유지하며 독립 임상 최종성능이나 모든 외부사진 성능으로 주장하지 않습니다. 별도 외부 여드름 사진을 건선 후보로 예측한 사례도 있어 실제촬영 입력 평가는 추가로 필요합니다. 이 패키지 실행검증은 성능 재측정이 아닙니다.

## 전달 구성과 복구

최신6클래스 best.pt, 독립적인backend_inference.py, 회귀검사, requirements.txt, 규격·예시·검증·학습validation/test 근거를 포함합니다. `disease_detection.py` 등 과거5클래스 학습코드는 런타임 의존성이 아닙니다. 원천사진·학습데이터·대용량ZIP·이전가중치·보정계수는 포함하지 않습니다.

manifest.json은 수록파일별 SHA256을 기록합니다. `.gitattributes`는 이 해시가 유지되도록 파일바이트를 보존합니다. 가중치는약5.5MB의실제파일로포함됩니다. 최신브랜치에서 제거한 이전5클래스 전달파일은 과거커밋1ae1287에서 복구할 수 있고 로컬 원본모델도 보존합니다. 별도 ZIP을 전달한다면 디렉터리구조를 유지해 추출하세요.
