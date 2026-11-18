
from pathlib import Path

from PIL import Image
from torch.utils.data import DataLoader
from torchvision import transforms

from .dataset import SkinDiseaseDataset


PROJECT_DIR = Path(__file__).resolve().parent.parent
ENCODED_DIR = PROJECT_DIR / "data" / "processed" / "encoded"

IMAGE_SIZE = 224
BATCH_SIZE = 32
NUM_WORKERS = 0


class AspectRatioResizePad:
    """
    이미지의 가로세로 비율을 유지하면서
    224x224 크기의 정사각형 캔버스에 배치한다.
    """

    def __init__(self, size=224, fill=(128, 128, 128)):
        self.size = size
        self.fill = fill

    def __call__(self, image):

        image = image.convert("RGB")

        original_width, original_height = image.size

        scale = min(
            self.size / original_width,
            self.size / original_height
        )

        new_width = max(1, round(original_width * scale))
        new_height = max(1, round(original_height * scale))

        image = image.resize(
            (new_width, new_height),
            Image.Resampling.BICUBIC
        )

        canvas = Image.new(
            "RGB",
            (self.size, self.size),
            self.fill
        )

        left = (self.size - new_width) // 2
        top = (self.size - new_height) // 2

        canvas.paste(image, (left, top))

        return canvas


# 비율 유지 전처리
resize_pad = AspectRatioResizePad(
    size=IMAGE_SIZE,
    fill=(128, 128, 128)
)


# 학습 데이터 증강
train_transform_aspect = transforms.Compose([
    resize_pad,

    transforms.RandomRotation(
        degrees=5,
        fill=(128, 128, 128)
    ),

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


# 검증 및 테스트 데이터 전처리
eval_transform_aspect = transforms.Compose([
    resize_pad,

    transforms.ToTensor(),

    transforms.Normalize(
        mean=[0.485, 0.456, 0.406],
        std=[0.229, 0.224, 0.225],
    ),
])


def get_aspect_dataloaders():

    train_dataset = SkinDiseaseDataset(
        ENCODED_DIR / "frontal_train_grouped.csv",
        transform=train_transform_aspect,
    )

    val_dataset = SkinDiseaseDataset(
        ENCODED_DIR / "frontal_val_grouped.csv",
        transform=eval_transform_aspect,
    )

    test_dataset = SkinDiseaseDataset(
        ENCODED_DIR / "frontal_test_grouped.csv",
        transform=eval_transform_aspect,
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
