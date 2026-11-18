# Frontal Aug A Validation

## 1. 실험 목적
기존 Frontal Crop 모델의 학습 데이터 증강 방식에 추가적인 변환을 적용한 Aug A 모델을 학습하고, 검증 데이터를 이용해 분류 성능을 평가한다.

## 2. 데이터 증강 방식
- 이미지 크기: 224×224
- RandomRotation: ±5°
- RandomAffine:
  - 이동 범위: 가로·세로 최대 3%
  - 크기 변환: 95~105%
- ColorJitter:
  - Brightness: 0.08
  - Contrast: 0.08
  - Saturation: 0.05
- 정규화: ImageNet Mean / Std

※ 데이터 증강은 학습 데이터에만 적용하며, 검증 데이터에는 적용하지 않는다.

## 3. 모델 및 평가
- 모델: ResNet50
- 입력 데이터: 정면 얼굴 크롭 이미지
- 검증 데이터: frontal_val_grouped.csv
- 검증 이미지: 430장
- 정답 이미지: 377장
- 오분류 이미지: 53장
- Validation Accuracy: 87.67%

## 4. 주요 분석 내용
- 질환별 분류 성능 분석
- 혼동 행렬 분석
- 오분류 이미지 데이터 및 JSON 점검
- 그룹별 정답 및 오답 분석
- 동일 그룹 내 복수 질환 라벨 사례 확인

## 5. 결과 파일
- frontal_aug_a_validation_predictions.csv
- frontal_aug_a_validation_misclassified.csv
- frontal_aug_a_validation_classification_report.csv
- frontal_aug_a_validation_confusion_matrix.csv
- frontal_aug_a_validation_data_audit.csv
- frontal_aug_a_validation_group_images.csv
- frontal_aug_a_validation_group_summary.csv
- frontal_aug_a_validation_error_groups.csv
- frontal_aug_a_validation_mixed_disease_groups.csv

## 6. 관련 코드
- src/train_frontal_aug_a.py
- src/dataloader_frontal_aug_a.py
- src/evaluate_frontal_aug_a_validation.py
- src/audit_frontal_aug_a_validation_errors.py
- src/analyze_frontal_aug_a_validation_groups.py

## 7. 참고 사항
본 결과는 검증 데이터 430장을 이용한 평가 결과이다. 테스트 데이터 성능과는 구분하여 해석한다.
