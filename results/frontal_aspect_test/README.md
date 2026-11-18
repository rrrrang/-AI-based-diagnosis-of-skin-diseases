# Frontal Aspect Ratio Test

## 1. 실험 목적
정면 얼굴 이미지를 모델 입력 크기인 224×224로 변환하는 과정에서 원본 이미지의 가로세로 비율을 유지하는 전처리 방식을 적용하고, ResNet50 모델의 분류 성능을 평가한다.

## 2. 전처리 방식
- 입력 이미지: 정면 얼굴 이미지
- 이미지 크기: 224×224
- 색상: RGB
- 리사이즈: 원본 이미지의 종횡비 유지
- 패딩: 이미지 중앙 배치 후 남는 영역을 RGB (128, 128, 128)로 채움
- 보간 방식: BICUBIC
- 정규화: ImageNet Mean / Std

## 3. 모델 및 평가
- 모델: ResNet50
- 평가 데이터: frontal_test_grouped.csv
- 테스트 이미지: 441장
- 정답 이미지: 382장
- 오분류 이미지: 59장
- Test Accuracy: 86.62%

## 4. 결과 파일

| 파일명 | 설명 |
|---|---|
| aspect_test_classification_report.csv | 질환별 분류 성능 |
| aspect_test_confusion_matrix.csv | 실제 라벨과 예측 라벨 비교 |
| aspect_test_confusion_matrix.png | 혼동 행렬 시각화 |
| aspect_test_predictions.csv | 전체 테스트 이미지 예측 결과 |
| aspect_test_misclassified.csv | 오분류 이미지 목록 |

## 5. 관련 코드
- src/train_aspect.py
- src/dataloader_aspect.py
- src/check_aspect_checkpoint.py
- src/evaluate_frontal_aspect.py
- src/compare_aspect_preprocessing.py

## 6. 참고 사항
본 실험은 기존 정면 이미지 테스트 데이터 441장을 사용한 평가이다. 동일한 테스트 데이터가 다른 실험에서도 사용되었으므로, 독립적인 신규 테스트 결과로 해석하지 않는다.
