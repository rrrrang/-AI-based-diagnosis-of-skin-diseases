
from pathlib import Path

import pandas as pd
import matplotlib.pyplot as plt

from PIL import Image
from torchvision import transforms

from src.dataloader_aspect import AspectRatioResizePad


PROJECT_DIR = Path(__file__).resolve().parent.parent

CSV_PATH = (
    PROJECT_DIR
    / "data"
    / "processed"
    / "encoded"
    / "frontal_test_grouped.csv"
)

OUTPUT_DIR = PROJECT_DIR / "results" / "aspect_preprocessing"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


# 비교할 이미지 수
NUM_IMAGES = 5

# 기존 전처리
old_transform = transforms.Resize((224, 224))

# 새로운 전처리
new_transform = AspectRatioResizePad(
    size=224,
    fill=(128, 128, 128)
)


def main():

    df = pd.read_csv(CSV_PATH)

    print(f"테스트 데이터: {len(df)}개")

    # 질환별로 이미지가 골고루 선택되도록 추출
    selected = (
        df.groupby("disease", group_keys=False)
        .head(1)
        .head(NUM_IMAGES)
        .reset_index(drop=True)
    )

    fig, axes = plt.subplots(
        len(selected),
        3,
        figsize=(12, 4 * len(selected))
    )

    if len(selected) == 1:
        axes = [axes]

    for index, row in selected.iterrows():

        image_path = Path(row["path"])

        if not image_path.is_absolute():
            image_path = PROJECT_DIR / image_path

        with Image.open(image_path) as img:
            original = img.convert("RGB")

        old_image = old_transform(original)
        new_image = new_transform(original)

        axes[index][0].imshow(original)
        axes[index][0].set_title(
            f"Original\n{row['disease']}"
        )

        axes[index][1].imshow(old_image)
        axes[index][1].set_title(
            "Old: Resize 224x224"
        )

        axes[index][2].imshow(new_image)
        axes[index][2].set_title(
            "New: Aspect Ratio + Padding"
        )

        for ax in axes[index]:
            ax.axis("off")

        print(
            f"{index + 1}. {row['disease']} | "
            f"원본 크기: {original.size}"
        )

    plt.tight_layout()

    save_path = OUTPUT_DIR / "aspect_preprocessing_comparison.png"

    plt.savefig(
        save_path,
        dpi=150,
        bbox_inches="tight"
    )

    plt.show()

    print("\n비교 이미지 저장 완료")
    print(save_path)


if __name__ == "__main__":
    main()
