import os
import random
from pathlib import Path

import pandas as pd
import torch
from PIL import Image
from torch.utils.data import Dataset, DataLoader
from torchvision import transforms as T

MEAN, STD = [0.485, 0.456, 0.406], [0.229, 0.224, 0.225]   # ImageNet 사전학습 모델 기준
GRAY = os.environ.get("SKIN_GRAY") == "1"                  # 회색조 실험 스위치
ROBUST = os.environ.get("SKIN_AUG") == "robust"            # 강건성 증강 스위치


class ChannelGain:
    """조명 색온도 변화를 흉내: R, B 채널 이득을 무작위로 바꿈 (PIL RGB 이미지용)."""

    def __init__(self, lo=0.88, hi=1.12):
        self.lo, self.hi = lo, hi

    def __call__(self, img):
        gr, gb = random.uniform(self.lo, self.hi), random.uniform(self.lo, self.hi)
        r, g, b = img.split()
        return Image.merge("RGB", (r.point(lambda v: min(255, int(v * gr))),
                                   g,
                                   b.point(lambda v: min(255, int(v * gb)))))


def get_transforms(img_size=224):
    gray = [T.Grayscale(3)] if GRAY else []
    robust = ([ChannelGain(),
               T.RandomApply([T.GaussianBlur(9, sigma=(0.3, 1.5))], p=0.3)]
              if ROBUST else [])
    train_tf = T.Compose([
        T.RandomResizedCrop(img_size, scale=(0.6, 1.0), ratio=(0.9, 1.1)),
        T.RandomHorizontalFlip(),
        T.RandomVerticalFlip(),
        T.RandomRotation(20),
        T.ColorJitter(brightness=0.15, contrast=0.15, saturation=0.1, hue=0.02),  # 색은 약하게
        *robust,
        *gray,
        T.ToTensor(),
        T.Normalize(MEAN, STD),
    ])
    eval_tf = T.Compose([
        T.Resize((img_size, img_size)),
        *gray,
        T.ToTensor(),
        T.Normalize(MEAN, STD),
    ])
    return train_tf, eval_tf


class SkinDataset(Dataset):
    def __init__(self, df, transform):
        self.paths = df["img_path"].tolist()
        self.labels = df["label_id"].tolist()
        self.transform = transform

    def __len__(self):
        return len(self.paths)

    def __getitem__(self, i):
        img = Image.open(self.paths[i]).convert("RGB")   # RGBA -> RGB
        return self.transform(img), self.labels[i]


def get_loaders(meta_csv, img_size=224, batch_size=32, num_workers=4):
    df = pd.read_csv(meta_csv, keep_default_na=False)
    train_tf, eval_tf = get_transforms(img_size)
    sets = {s: df[df["set"] == s] for s in ["train", "val", "test"]}
    pin = torch.cuda.is_available()
    loaders = {
        "train": DataLoader(SkinDataset(sets["train"], train_tf), batch_size=batch_size,
                            shuffle=True, num_workers=num_workers, pin_memory=pin),
        "val": DataLoader(SkinDataset(sets["val"], eval_tf), batch_size=batch_size,
                          shuffle=False, num_workers=num_workers, pin_memory=pin),
        "test": DataLoader(SkinDataset(sets["test"], eval_tf), batch_size=batch_size,
                           shuffle=False, num_workers=num_workers, pin_memory=pin),
    }
    return loaders


if __name__ == "__main__":      # Windows에서는 num_workers>0일 때 이 가드가 필요합니다
    OUT = Path(__file__).resolve().parent.parent / "outputs"
    loaders = get_loaders(os.path.join(OUT, "meta_split_block.csv"))
    x, y = next(iter(loaders["train"]))
    print(x.shape, y[:10], x.min().item(), x.max().item(), "| GRAY:", GRAY, "| ROBUST:", ROBUST)
