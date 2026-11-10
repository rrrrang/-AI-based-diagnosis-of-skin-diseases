# 피부 질환 분류 모델 (v0.1)

합성 피부 이미지(병변 확대)를 6개 클래스로 분류하는 연구용 모델입니다. 성능과 한계는 `MODEL_CARD.md`를 먼저 읽어 주세요.
**의학적 진단 도구가 아니며, 비상업적 모델 개발·연구 목적으로만 사용하세요.**

## 폴더
```
configs/    학습 설정 (final_v0_1.json)
scripts/    학습·평가·추론 코드
data_prep/  데이터 범위·분할 생성 스크립트
model/      체크포인트, 판단 불가 기준, 라벨 맵, manifest
reports/    평가 결과 (시드별, 요약)
splits/     분할 목록 (이미지 없음: id, 라벨, 세트, 해시, 블록)
```

## 설치
```
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```
CPU용 torch는 `--index-url https://download.pytorch.org/whl/cpu`로 설치할 수 있습니다.

## 추론
```
python scripts/predict.py --image <사진 경로> [--cam 저장경로.png]
```
Python에서는 `from inference_core import Predictor; Predictor().predict(PIL 이미지)`가
`names, probs, top3, pred, conf, threshold, accepted, warnings, overlay`를 담은 dict를 돌려줍니다.
`accepted=False`이면 "판단 불가"로 처리해야 합니다. 웹 데모: `python scripts/demo_app.py` (로컬 전용)

## 데이터 준비 (data_prep/)
데이터는 저장소에 없습니다. AI 허브 '안면부 피부질환 이미지 합성 데이터'(dataSetSn=71863)를 이용 조건에 따라 직접 받아
`data/{Training,Validation}/{01.원천데이터,02.라벨링데이터}/...` 구조로 두세요.
```
python data_prep/01_validate_data.py    # outputs/meta.csv, outputs/label2id.json (측면 Z4_ 파일만, 해시·크기 검사)
python data_prep/02_split.py            # outputs/meta_split.csv (무작위 분할, 참고용)
python data_prep/02b_split_block.py     # outputs/meta_split_block.csv (공식 분할)
```
분할 재현 확인:
```
python -c "import pandas as pd; a=pd.read_csv('outputs/meta_split_block.csv',keep_default_na=False)[['id','set']].sort_values('id').reset_index(drop=True); b=pd.read_csv('splits/split_block_v1.csv',keep_default_na=False)[['id','set']].sort_values('id').reset_index(drop=True); print('분할 일치' if a.equals(b) else '분할 불일치')"
```

## 학습·평가
```
python scripts/train.py --config configs/final_v0_1.json --seeds 42 43 44
python scripts/robustness_test.py --ckpt runs/final_v0_1/seed_42/best.pt
python scripts/summarize_runs.py
```
- 산출물: `outputs/runs/<실행>/seed_<n>/` (best.pt, threshold.json, test_report.json, config_resolved.json, history.csv ...)
- 학습 시작 전에 데이터 검증을 수행하며, 실패하면 ValueError로 비정상 종료합니다.
- 완료된 시드는 다시 실행해도 건너뜁니다 (`--force`로 재학습).
- `threshold.json`은 체크포인트와 한 쌍입니다. 재학습하면 함께 다시 만들어집니다.
- 릴리스 패키지 생성: `python scripts/make_release.py --run final_v0_1 --seed 42` (공개 저장소용은 `--no-splits`), 무결성 확인: `python scripts/verify_release.py` (불일치 시 종료 코드 1)

## 데이터 계약
- meta CSV 필수 컬럼: id, label, label_id, img_path, set(train/val/test), md5 (블록 분할이면 blk)
- 범위: 측면 이미지(파일명 `Z4_` 접두사), 512×512 RGB, 6개 클래스, 클래스당 900장
- 분할 규칙: ID 숫자를 50 단위로 묶은 블록 단위, 같은 md5는 같은 세트, 중복 정리로 5,400장 중 24장 제외, 클래스 층화
- 학습 시작 시 자동 검증: 라벨-label_id 일치, 이미지 파일 존재, 세트 간 md5·블록 겹침 0

## 품질 게이트 초안 (확정은 파이프라인 담당)
| 지표 | 초안 기준 | v0.1 관측치 |
|---|---|---|
| test 정확도 | 98.5% 이상 | 99.50~99.83% |
| 클래스별 recall | 0.95 이상 | 최소 0.97 (아토피) |
| 일반 화질 교란(밝기·색·감마·흐림 등) | 원본 대비 -3%p 이내 | 최대 -1.84%p |
| JPEG 품질 40 / 20 | 94% / 88% 이상 | 96.99% / 91.82% |
| 판단 불가 | 정답 예측 통과율 93% 이상, 통과 예측 정확도 99.5% 이상 | 94.3%, 100% |

중앙 가림과 JPEG 품질 10은 참고 지표로만 보고합니다. 평가 데이터가 599장이라 기준에는 여유를 두었습니다.

## 이용 조건과 출처
- 데이터 설명서 기준 상업적 이용이 아닌 모델 개발·학습 목적의 사용이 허용됩니다 (확인 2026-11-09). 상업적 이용은 별도 협의가 필요합니다.
- 본 모델은 AI 허브(aihub.or.kr)에서 제공하는 '안면부 피부질환 이미지 합성 데이터'를 활용하여 개발되었습니다.
- 데이터 이미지는 이 저장소에 포함하지 않습니다.

## 알려진 이슈
합성 데이터 한정 성능(실제 사진 미검증), JPEG 압축·부분 가림 취약, 원본 대응 정보 없음, 분포 밖 입력 정량 평가 없음 (자세히는 `MODEL_CARD.md`)