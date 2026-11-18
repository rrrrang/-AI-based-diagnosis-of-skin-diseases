# Frontal Aug A Model Comparison

## 1. 실험 목적
기존 Frontal Crop 모델과 Aug A 모델의 성능을 동일한 테스트 데이터로 비교하여 데이터 증강 방식의 성능 차이를 확인한다.

## 2. 비교 모델

### Baseline: Frontal Crop
- 모델: ResNet50
- 기본 이미지 크기 조정 방식: Resize(224, 224)
- ImageNet Mean / Std 정규화

### Experiment: Frontal Aug A
- 모델: ResNet50
- RandomRotation: ±5°
- RandomAffine:
  - 이동 범위: 가로·세로 최대 3%
  - 크기 변환: 95~105%
- ColorJitter:
  - Brightness: 0.08
  - Contrast: 0.08
  - Saturation: 0.05

※ 증강은 학습 데이터에만 적용하며 테스트 데이터에는 적용하지 않는다.

## 3. 테스트 데이터
- 데이터 파일: frontal_test_grouped.csv
- 테스트 이미지: 441장
- 두 모델 모두 동일한 테스트 데이터로 평가

## 4. 테스트 성능 비교

| 평가 항목 | Frontal Crop | Frontal Aug A |
|---|---:|---:|
| 테스트 이미지 | 441 | 441 |
| 정답 이미지 | 382 | 392 |
| 오분류 이미지 | 59 | 49 |
| Test Accuracy | 86.62% | 88.89% |

- 정확도 차이: +2.27%p
- 정답 이미지: 10장 증가
- 오분류 이미지: 10장 감소

## 5. 주요 분석 내용
- 모델별 질환 분류 성능 비교
- 혼동 행렬 비교
- 이미지별 예측 결과 비교
- 두 모델의 공통 오분류 이미지 분석
- 이미지 품질 및 JSON 라벨 점검

## 6. 결과 파일
- frontal_aug_a_comparison.csv
- frontal_crop_classification_report.csv
- frontal_aug_a_classification_report.csv
- frontal_crop_confusion_matrix.csv
- frontal_aug_a_confusion_matrix.csv
- frontal_crop_predictions.csv
- frontal_aug_a_predictions.csv
- frontal_crop_misclassified.csv
- frontal_aug_a_misclassified.csv
- image_prediction_comparison.csv
- both_models_wrong.csv
- frontal_aug_a_data_audit.csv
- frontal_aug_a_image_quality.csv
- frontal_aug_a_json_audit.csv

※ 이미지 검토용 파일과 Contact Sheet도 포함한다.

## 7. 관련 코드
- src/compare_frontal_aug_a.py

## 8. 참고 사항
본 비교는 기존에 사용한 테스트 데이터 441장을 대상으로 수행한 결과이다. 따라서 독립적인 신규 테스트 데이터에 대한 성능 검증으로 해석하지 않는다.
