import pandas as pd
from pathlib import Path

BASE_DIR = Path(r"D:\skin-disease-ai")
INPUT_PATH = BASE_DIR / "data/processed/encoded/labeling_metadata_side.csv"
OUTPUT_PATH = BASE_DIR / "data/processed/encoded/labeling_metadata_side_clean.csv"

# CSV 불러오기
df = pd.read_csv(INPUT_PATH)

# 삭제할 컬럼
drop_columns = [
    "diagnosis_name",
    "diagnosis_bodypart",
    "gender",
    "generated_bodypart"
]

# 실제 존재하는 컬럼만 삭제
df = df.drop(columns=drop_columns, errors="ignore")

# 저장
df.to_csv(OUTPUT_PATH, index=False, encoding="utf-8-sig")

print("삭제 후 컬럼 목록:")
print(df.columns.tolist())

print(f"\n데이터 행 개수: {len(df)}")
print(f"저장 완료: {OUTPUT_PATH}")