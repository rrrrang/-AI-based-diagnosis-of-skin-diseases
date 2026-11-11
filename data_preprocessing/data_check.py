
from pathlib import Path
import pandas as pd

PROJECT_DIR = Path(__file__).resolve().parent.parent

FILES = {
    "원본 메타데이터": PROJECT_DIR / "data" / "processed" / "metadata_deduplicated.csv",
    "라벨링 메타데이터": PROJECT_DIR / "data" / "processed" / "labeling_metadata.csv",
    "Train": PROJECT_DIR / "data" / "processed" / "encoded" / "train.csv",
    "Validation": PROJECT_DIR / "data" / "processed" / "encoded" / "val.csv",
    "Test": PROJECT_DIR / "data" / "processed" / "encoded" / "test.csv",
}

for name, file_path in FILES.items():
    print("\n" + "=" * 60)
    print(f"[{name}]")
    print("=" * 60)

    if not file_path.exists():
        print(f"파일 없음: {file_path}")
        continue

    df = pd.read_csv(file_path)

    print(f"파일 경로: {file_path}")
    print(f"데이터 행 수: {len(df):,}")
    print(f"컬럼: {df.columns.tolist()}")

    if "disease" in df.columns:
        print("\n질환별 데이터 수:")
        print(df["disease"].value_counts().sort_index())

    if "view" in df.columns:
        print("\n촬영 방향별 데이터 수:")
        print(df["view"].value_counts(dropna=False))

    if "path" in df.columns:
        print("\n이미지 경로 예시:")
        print(df["path"].head(3).to_list())
