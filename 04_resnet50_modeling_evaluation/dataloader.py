
from pathlib import Path

from torch.utils.data import DataLoader
from torchvision import transforms

from .dataset import (
    SkinDiseaseDataset,
    base_transform,
)

PROJECT_DIR = Path(__file__).resolve().parent.parent
ENCODED_DIR = PROJECT_DIR / "data" / "processed" / "encoded"


BATCH_SIZE = 32
NUM_WORKERS = 0


# 정면 + 측면 통합 학습 데이터 증강
train_transform = transforms.Compose([
    transforms.Resize((224, 224)),

    transforms.RandomRotation(degrees=5),

    transforms.ColorJitter(
        brightness=0.08,
        contrast=0.08,
        saturation=0.05,
    ),

    transforms.ToTensor(),

    transforms.Normalize(
        mean=[0.485, 0.456, 0.406],
        std=[0.229, 0.224, 0.225],
    ),
])



def get_dataloaders():

    # 정면 Crop 학습 데이터
    train_dataset = SkinDiseaseDataset(
        ENCODED_DIR / "frontal_train_grouped.csv",
        transform=train_transform,
    )

    # 정면 Crop 검증 데이터
    val_dataset = SkinDiseaseDataset(
        ENCODED_DIR / "frontal_val_grouped.csv",
        transform=base_transform,
    )

    # 정면 Crop 테스트 데이터
    test_dataset = SkinDiseaseDataset(
        ENCODED_DIR / "frontal_test_grouped.csv",
        transform=base_transform,
    )

    train_loader = DataLoader(
        train_dataset,
        batch_size=BATCH_SIZE,
        shuffle=True,
        num_workers=NUM_WORKERS,
    )

    val_loader = DataLoader(
        val_dataset,
        batch_size=BATCH_SIZE,
        shuffle=False,
        num_workers=NUM_WORKERS,
    )

    test_loader = DataLoader(
        test_dataset,
        batch_size=BATCH_SIZE,
        shuffle=False,
        num_workers=NUM_WORKERS,
    )

    return train_loader, val_loader, test_loader

