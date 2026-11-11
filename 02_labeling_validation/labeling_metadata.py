## 라벨링 JSON 9,600개 통합 및 메타데이터 생성

import json
import pandas as pd
from pathlib import Path

BASE = Path(r"D:\skin-disease-ai\data\processed\images")
OUT = Path(r"D:\skin-disease-ai\data\processed")

OUT.mkdir(parents=True, exist_ok=True)

records = []
errors = []

# 라벨링데이터 12개 폴더 순회
for folder in sorted(BASE.glob("TL_*")):

    if not folder.is_dir():
        continue

    parts = folder.name.split("_", 2)

    if len(parts) != 3:
        print(f"[경고] 폴더명 확인 필요: {folder.name}")
        continue

    prefix, folder_disease, folder_view = parts

    print(f"처리 중: {folder.name}")

    for json_path in sorted(folder.rglob("*.json")):

        try:
            with open(json_path, "r", encoding="utf-8-sig") as f:
                data = json.load(f)

            annotations = data.get("annotations", [])

            if not isinstance(annotations, list) or not annotations:
                errors.append({
                    "json_path": str(json_path),
                    "error": "annotations 누락 또는 비어 있음"
                })
                continue

            for annotation in annotations:

                diagnosis = annotation.get("diagnosis_info") or {}
                generated = annotation.get("generated_parameters") or {}
                photograph = annotation.get("photograph") or {}
                bbox = annotation.get("bbox") or {}

                # JSON 내부 정보를 하나의 행으로 통합
                record = {
                    # 기본 정보
                    "identifier": annotation.get("identifier"),
                    "disease": folder_disease,
                    "view": folder_view,
                    "json_path": str(json_path),

                    # 진단 정보
                    "diagnosis_name": diagnosis.get("diagnosis_name"),
                    "diagnosis_bodypart": diagnosis.get("bodypart"),
                    "desc": diagnosis.get("desc"),

                    # 생성 파라미터
                    "gender": generated.get("gender"),
                    "generated_bodypart": generated.get("bodypart"),

                    # 이미지 정보
                    "photograph_file_path": photograph.get("file_path"),
                    "photograph_width": photograph.get("width"),
                    "photograph_height": photograph.get("height")
                }
                records.append(record)

        except Exception as e:
            errors.append({
                "json_path": str(json_path),
                "error": str(e)
            })

# DataFrame 생성
df = pd.DataFrame(records)

# CSV 저장
output_file = OUT / "labeling_metadata.csv"
df.to_csv(output_file, index=False, encoding="utf-8-sig")

# 오류 목록 저장
if errors:
    error_file = OUT / "labeling_errors.csv"
    pd.DataFrame(errors).to_csv(
        error_file, index=False, encoding="utf-8-sig"
    )

# 결과 확인
print("\n" + "=" * 60)
print("라벨링 메타데이터 통합 결과")
print("=" * 60)

print(f"전체 데이터: {len(df):,}개")
print(f"전체 컬럼: {len(df.columns)}개")
print(f"오류 파일: {len(errors):,}개")

if not df.empty:
    print("\n[질환별 데이터]")
    print(df["disease"].value_counts())

    print("\n[촬영 방향별 데이터]")
    print(df["view"].value_counts())

    print("\n[진단명 불일치]")
    mismatch = df[
        df["disease"] != df["diagnosis_name"]
    ]
    print(f"{len(mismatch):,}개")

print(f"\n저장 위치: {output_file}")
print("=" * 60)
