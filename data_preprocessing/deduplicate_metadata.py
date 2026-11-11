
from pathlib import Path
import pandas as pd

PROJECT_DIR = Path(__file__).resolve().parent.parent
INPUT_CSV = PROJECT_DIR / "data" / "processed" / "metadata.csv"
OUTPUT_DIR = PROJECT_DIR / "data" / "processed" / "quality_check"

CLEAN_CSV = OUTPUT_DIR / "metadata_deduplicated.csv"
REMOVED_CSV = OUTPUT_DIR / "duplicate_rows_to_review.csv"


def main():
    df = pd.read_csv(INPUT_CSV, encoding="utf-8-sig")

    # 해시가 있는 행만 중복 판정에 사용
    has_hash = (
        df["sha256"].notna()
        & df["sha256"].astype(str).ne("")
    )

    # 동일한 해시의 첫 번째 행만 유지
    duplicate_mask = pd.Series(False, index=df.index)
    duplicate_mask.loc[has_hash] = (
        df.loc[has_hash, "sha256"].duplicated(keep="first")
    )

    # 원본 CSV는 수정하지 않음
    clean_df = df.loc[~duplicate_mask].copy()
    removed_df = df.loc[duplicate_mask].copy()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    clean_df.to_csv(
        CLEAN_CSV, index=False, encoding="utf-8-sig"
    )
    removed_df.to_csv(
        REMOVED_CSV, index=False, encoding="utf-8-sig"
    )

    print("===== 중복 제외 결과 =====")
    print(f"원본 행 수: {len(df):,}")
    print(f"중복 후보로 제외한 행 수: {len(removed_df):,}")
    print(f"중복 제외 후 행 수: {len(clean_df):,}")

    print("\n===== 질환별 행 수 =====")
    print(clean_df["disease"].value_counts().to_string())

    print(f"\n중복 제외 CSV: {CLEAN_CSV}")
    print(f"검토용 목록: {REMOVED_CSV}")


if __name__ == "__main__":
    main()
