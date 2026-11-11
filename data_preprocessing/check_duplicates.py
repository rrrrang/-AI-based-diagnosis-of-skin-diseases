
from pathlib import Path
import pandas as pd

PROJECT_DIR = Path(__file__).resolve().parent.parent
CSV_PATH = PROJECT_DIR / "data" / "processed" / "metadata.csv"
OUTPUT_DIR = PROJECT_DIR / "data" / "processed" / "quality_check"


def main():
    df = pd.read_csv(CSV_PATH, encoding="utf-8-sig")

    # 유효한 SHA-256 해시가 있는 행만 검사
    valid = df[
        df["sha256"].notna()
        & df["sha256"].astype(str).ne("")
    ].copy()

    # 같은 해시가 2번 이상 등장하는 그룹
    duplicated = valid[
        valid.duplicated("sha256", keep=False)
    ].copy()

    if duplicated.empty:
        print("중복 이미지가 발견되지 않았습니다.")
        return

    # 중복 그룹별 통계
    summary = (
        duplicated.groupby("sha256")
        .agg(
            row_count=("path", "size"),
            image_names=("image_name", lambda x: " | ".join(x)),
            paths=("path", lambda x: " | ".join(x)),
            diseases=("disease", lambda x: " | ".join(sorted(set(x.dropna())))),
            disease_count=("disease", "nunique"),
        )
        .reset_index()
    )

    summary["cross_disease"] = summary["disease_count"] > 1

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    summary.to_csv(
        OUTPUT_DIR / "duplicate_groups.csv",
        index=False,
        encoding="utf-8-sig",
    )

    duplicated.to_csv(
        OUTPUT_DIR / "duplicate_rows.csv",
        index=False,
        encoding="utf-8-sig",
    )

    print("===== 중복 분석 결과 =====")
    print(f"중복 관련 행 수: {len(duplicated)}")
    print(f"중복 그룹 수: {len(summary)}")
    print(
        "서로 다른 질환 폴더에 걸친 중복 그룹:",
        int(summary["cross_disease"].sum()),
    )

    print("\n===== 중복 그룹 상세 =====")
    print(summary.to_string(index=False))

    print("\n저장 완료:")
    print(OUTPUT_DIR / "duplicate_groups.csv")
    print(OUTPUT_DIR / "duplicate_rows.csv")


if __name__ == "__main__":
    main()
