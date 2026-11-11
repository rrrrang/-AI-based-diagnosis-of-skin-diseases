import pandas as pd
from pathlib import Path

BASE_DIR = Path(r"D:\skin-disease-ai")

FILE_PATH = (
    BASE_DIR
    / "data/processed/encoded/labeling_metadata_side_clean.csv"
)

df = pd.read_csv(FILE_PATH)

print("===== 데이터 기본 정보 =====")
print("전체 행:", len(df))
print("전체 컬럼:", len(df.columns))
print("컬럼 목록:", df.columns.tolist())

print("\n===== 결측값 확인 =====")
print(df.isnull().sum())

print("\n===== 중복 데이터 확인 =====")
print("전체 행 중복:", df.duplicated().sum())
print("식별자 중복:", df["identifier"].duplicated().sum())

print("\n===== 촬영 방향 확인 =====")
print(df["view"].value_counts(dropna=False))

print("\n===== 질환별 데이터 개수 =====")
print(df["disease"].value_counts(dropna=False))

print("\n===== 데이터 샘플 =====")
print(df.head())