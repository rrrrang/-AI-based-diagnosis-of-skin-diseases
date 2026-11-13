# 측면·근접 이미지 앙상블

YOLO11n, MobileNetV3, 측면 ResNet50의 체크포인트로 같은 사진을 추론합니다. 각 모델의 1위 후보를 공통 코드로 변환한 뒤 모델별 기준을 통과한 후보에 한 표를 줍니다. 출력 JSON에는 결과, 표 수, 개별 모델의 원점수와 적용 기준이 포함됩니다.

## 준비 및 실행

Git LFS를 설치하고 아래 세 브랜치를 각각 별도 폴더로 내려받습니다. 체크포인트가 Git LFS 포인터 대신 실제 파일로 내려왔는지 확인합니다.

- `feature/skin-classifier-v0.1` → MobileNet 폴더
- `feature/skin-data-processing-resnet50` → ResNet 폴더
- `feature/skin-YOLO11n` → YOLO 폴더

Python 3.12 가상환경에서 CPU용 PyTorch와 나머지 추론 의존성을 설치합니다.

```powershell
python -m pip install --index-url https://download.pytorch.org/whl/cpu torch torchvision
python -m pip install ultralytics==8.4.198 matplotlib tzdata
```

임계값 JSON은 다음 구조를 사용합니다. `ensemble/thresholds.example.json`은 통합 실행에 사용한 예시입니다. 실제 평가에는 세 모델에 공통인 검증셋에서 정한 모델별 원점수 기준을 넣으세요.

```json
{"mobilenet": 0.82, "resnet50": 0.85, "yolo": 0.70}
```

작업공간 루트에서 실행합니다.

```powershell
python -m ensemble --image photo.png --role side_closeup --mobilenet-root D:/models/mobile --resnet-root D:/models/resnet --yolo-root D:/models/yolo --thresholds thresholds.json
python -m unittest ensemble.test_policy
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
- `deferred`는 다수결 없이 기준을 통과한 서로 다른 후보가 여러 개이거나, 분류기 두 개가 모두 정상에 투표했으나 YOLO가 질환을 검출한 경우입니다.
- `normal_consensus`는 분류기 두 개가 모두 정상에 투표하고 YOLO가 미검출인 경우입니다. 정상 합의는 YOLO의 원래 검출 결과를 확인하므로 투표 기준 미달인 검출도 보류 사유입니다.
- `undetermined`는 채택할 후보가 없는 경우입니다.
- `unsupported_input`은 정면 사진입니다.

실제 모델 성능은 모델별 기준을 정한 뒤, 그 과정에 사용하지 않은 공통 측면 테스트셋에서 평가합니다.
