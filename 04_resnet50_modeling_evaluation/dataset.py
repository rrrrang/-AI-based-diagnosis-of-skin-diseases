
from pathlib import Path

import pandas as pd
import torch
from PIL import Image
from torch.utils.data import Dataset
from torchvision import transforms


PROJECT_DIR = Path(__file__).resolve().parent.parent

IMAGE_SIZE = 224
NUM_CLASSES = 6

DISEASE_LABELS = {
    "건선": 0,
    "아토피": 1,
    "여드름": 2,
    "정상": 3,
    "주사": 4,
    "지루": 5,
}

# 이미지 기본 전처리
base_transform = transforms.Compose([
    transforms.Resize((IMAGE_SIZE, IMAGE_SIZE)),
    transforms.ToTensor(),
    transforms.Normalize(
        mean=[0.485, 0.456, 0.406],
        std=[0.229, 0.224, 0.225]
    )
])


class SkinDiseaseDataset(Dataset):

    def __init__(self, csv_path, transform=None):
        self.df = pd.read_csv(csv_path)
        self.transform = (
            transform if transform is not None else base_transform
        )

        # 필수 컬럼 확인
        required_columns = {"path", "disease", "label"}
        missing = required_columns - set(self.df.columns)

        if missing:
            raise ValueError(
                f"CSV에 필요한 열이 없습니다: {sorted(missing)}"
            )

        # 결측값 확인
        if self.df["path"].isna().any():
            raise ValueError("이미지 경로에 결측값이 있습니다.")

        if self.df["label"].isna().any():
            raise ValueError("숫자 라벨에 결측값이 있습니다.")

        if self.df["disease"].isna().any():
            raise ValueError("질환명에 결측값이 있습니다.")

        # 숫자 라벨 변환 및 검증
        self.df["label"] = self.df["label"].astype(int)

        if not self.df["label"].between(0, NUM_CLASSES - 1).all():
            raise ValueError("label 값은 0~5 범위여야 합니다.")

        # 질환명과 숫자 라벨 일치 여부 확인
        expected_labels = self.df["disease"].map(DISEASE_LABELS)

        if expected_labels.isna().any():
            raise ValueError("알 수 없는 질환명이 있습니다.")

        if not (self.df["label"] == expected_labels).all():
            raise ValueError("질환명과 숫자 라벨이 일치하지 않습니다.")

    def __len__(self):
        return len(self.df)

    def __getitem__(self, index):
        row = self.df.iloc[index]

        image_path = Path(row["path"])

        if not image_path.is_absolute():
            image_path = PROJECT_DIR / image_path

        if not image_path.is_file():
            raise FileNotFoundError(
                f"이미지 파일을 찾을 수 없습니다: {image_path}"
            )

        # RGB 이미지 변환
        with Image.open(image_path) as img:
            image = img.convert("RGB")

        # 이미지 전처리
        if self.transform is not None:
            image = self.transform(image)

        # 숫자 라벨 생성
        label = torch.tensor(
            int(row["label"]),
            dtype=torch.long
        )

        return image, label
