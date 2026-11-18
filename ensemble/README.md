# 측면·근접 이미지 앙상블

YOLO11n, MobileNetV3, 측면 ResNet50의 체크포인트로 같은 사진을 추론합니다. 각 모델의 1위 후보를 공통 코드로 변환한 뒤 모델별 기준을 통과한 후보에 한 표를 줍니다. YOLO의 정상과 질환이 함께 검출되는 경우를 놓치지 않도록 1위 후보 외에 전체 6개 클래스 점수도 확인합니다.

아래 규칙은 **6개 클래스 모델을 연결하기 위한 임시 기술 기준**입니다. 의학적 정확도나 배포 적합성을 입증한 기준은 아니며, 최종 판단과 결과 전달은 의사가 담당합니다.

## 준비 및 실행

Git LFS를 설치하고 아래 세 브랜치를 각각 별도 폴더로 내려받습니다. 체크포인트가 Git LFS 포인터 대신 실제 파일로 내려왔는지 확인합니다.

- `feature/skin-classifier-v0.1` → MobileNet 폴더
- `feature/skin-data-processing-resnet50` → ResNet 폴더
- `feature/skin-YOLO11n` → YOLO 폴더

이 연결 코드의 YOLO 기준은 `27ef0b49c1dbfe40d45f3df22545fa0ed957abaa`의 schema `2.0` 응답입니다. 가중치는 `models/yolo11_detect/side_six_class_augmented/weights/best.pt`를 사용합니다. 이전 5개 클래스의 `side_hard_negative` 모델을 이 경로로 이름만 바꿔 사용하지 않습니다. CI의 고정 모델 묶음은 별도의 검증된 모델 목록과 해시를 따릅니다.

공통 라벨 순서는 `0=건선`, `1=아토피`, `2=여드름`, `3=정상`, `4=주사`, `5=지루`입니다. YOLO 응답은 검출되지 않은 클래스도 포함하여 `class_id`, `name`, `label`, `detected`, `score`가 있는 6개 행을 반환해야 합니다. 미검출은 `detected=false, score=null`이고, 미검출 자체를 정상으로 바꾸지 않습니다.

Python 3.12 가상환경에서 CPU용 PyTorch와 나머지 추론 의존성을 설치합니다.

```powershell
python -m pip install --index-url https://download.pytorch.org/whl/cpu torch torchvision
python -m pip install ultralytics==8.4.198 matplotlib tzdata
```

임계값 JSON은 다음 구조를 사용합니다. `ensemble/thresholds.example.json`의 `0.82/0.85/0.70`은 이번 연결에서 변경하지 않은 기존 예시값이며, 새 YOLO 모델의 성능 평가로 확정한 값이 아닙니다. 실제 평가에는 세 모델에 공통인 검증셋에서 정한 모델별 원점수 기준을 넣으세요.

```json
{"mobilenet": 0.82, "resnet50": 0.85, "yolo": 0.70}
```

작업공간 루트에서 실행합니다.

```powershell
python -m ensemble --image photo.png --role side_closeup --mobilenet-root D:/models/mobile --resnet-root D:/models/resnet --yolo-root D:/models/yolo --thresholds thresholds.json
python -m unittest ensemble.test_policy ensemble.test_inference_contract
```

로컬 AI Hub 합성 데이터의 측면 Validation 폴더를 일괄 추론하고 동일 사진에서 모델별 결과를 비교할 수 있습니다.

```powershell
python -m ensemble.batch --dataset D:/ddd/outputs/skin_augmented_v1 --output output/ensemble/validation-predictions.jsonl --mobilenet-root D:/models/mobile --resnet-root D:/models/resnet --yolo-root D:/models/yolo --thresholds ensemble/thresholds.example.json
python -m ensemble.metrics output/ensemble/validation-predictions.jsonl --expected-count 600 --output output/ensemble/validation-metrics.json
```

배치와 요약은 기존 결과 파일을 보호합니다. 재실행에는 새 출력 경로를 지정하세요. AI Hub의 Validation 폴더 구분과 각 모델이 사용한 분할은 다릅니다.

별도 측면 데이터는 `--dataset` 대신 `--manifest holdout.csv`로 전달합니다. CSV 열은 `image_id,path,label`이며 경로는 절대 경로 또는 CSV 위치 기준 상대 경로를 사용합니다. 라벨은 `psoriasis`, `atopic_dermatitis`, `acne`, `normal`, `rosacea`, `seborrheic_dermatitis` 중 하나입니다. 지표 요약의 `--expected-count`에는 CSV 이미지 수를 입력합니다.

## 결과

- `majority`는 같은 질환에 2표 이상 모인 경우입니다.
- `single_qualified`는 다수결 없이 채택 기준을 통과한 후보가 질환 하나뿐인 경우입니다. 모델 간 원점수 순위 비교는 필요하지 않습니다.
- `deferred`는 질환 다수결 없이 유효 후보가 서로 다르거나, 정상 표가 있으면서 YOLO가 질환도 검출한 경우입니다. YOLO 정상 점수가 가장 높더라도 다른 질환 검출을 숨기지 않습니다. YOLO 투표 기준 `0.70` 미만인 질환 검출도 정상 판정을 막습니다.
- `normal_consensus`는 세 모델 중 정상에 2표 이상, 유효한 질환 표 0개, YOLO의 원래 질환 검출 0개를 모두 만족한 경우입니다. YOLO도 정상에 한 표를 줄 수 있습니다. 정상 표 하나만으로는 정상 합의가 되지 않습니다.
- `undetermined`는 채택할 후보가 없거나 정상 표가 하나뿐이고 충돌할 질환 검출도 없는 경우입니다.
- `unsupported_input`은 정면 사진입니다.

출력의 `models.yolo`에는 임계값 적용 전 최고 후보가, `yolo_disease_scores`에는 정상과 미검출을 포함한 6개 행 전체가 남습니다. 점수는 보정되지 않은 검출 신뢰도로 합이 100%인 질환 확률이 아닙니다. 정상과 질환이 함께 검출되어도 다른 두 모델이 같은 질환에 유효한 2표를 주면 질환 `majority`는 유지합니다.

실제 통합 판정에는 `Ensemble.predict()` 또는 `predict_models_with_metadata()`와 `decide(..., yolo_disease_scores=...)`를 사용합니다. 이전 `predict_models()`는 개별 모델 조회 호환용이며 전체 점수를 전달하지 않으므로 새 정상 판정에 사용하지 않습니다. `decide`의 메타데이터 생략은 기존 합성 테스트 호환용입니다.

실제 모델 성능은 모델별 기준을 정한 뒤, 그 과정에 사용하지 않은 공통 측면 테스트셋에서 평가합니다. 기존 모델의 평가 파일을 새 모델의 성능 결과로 해석하지 않습니다.
