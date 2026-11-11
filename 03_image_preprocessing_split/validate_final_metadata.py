import pandas as pd
from pathlib import Path

BASE_DIR = Path(r"D:\skin-disease-ai")

FILE_PATH = (
    BASE_DIR / "data/processed/encoded/final_metadata.csv"
)

df = pd.read_csv(FILE_PATH)

print("===== 최종 메타데이터 검증 =====")

# 기본 정보
print("\n[기본 정보]")
print("전체 데이터:", len(df))
print("컬럼:", df.columns.tolist())

# 결측값
print("\n[결측값]")
print(df.isnull().sum())

# 중복
print("\n[중복 검사]")
print("중복 행:", df.duplicated().sum())
print("중복 이미지 ID:", df["image_id"].duplicated().sum())
print("중복 이미지 경로:", df["path"].duplicated().sum())

# 질환별 데이터
print("\n[질환별 데이터]")
print(df["disease"].value_counts())

# 라벨별 데이터
print("\n[라벨별 데이터]")
print(df.groupby(["label", "disease"]).size())

# 촬영 방향
print("\n[촬영 방향]")
print(df["view"].value_counts())

# 이미지 크기
print("\n[이미지 크기]")
print(df.groupby(["width", "height"]).size())

# 중복 해시
print("\n[SHA256 중복]")
print(df["sha256"].duplicated().sum())

print("\n검증 완료")