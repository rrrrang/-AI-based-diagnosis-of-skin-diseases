"""공용 라이브러리: 설정, 시드, 데이터 검증, 증강, 데이터셋, 모델, 평가 유틸. (환경변수 스위치 없음)"""
import hashlib
import json
import math
import platform
import random
import subprocess
from pathlib import Path

import numpy as np
import pandas as pd
import torch
import torch.nn as nn
from PIL import Image
from torch.utils.data import DataLoader, Dataset
from torchvision import models, transforms as T

PROJECT_ROOT = Path(__file__).resolve().parent.parent      # scripts의 상위 폴더 = 프로젝트 루트
MEAN, STD = [0.485, 0.456, 0.406], [0.229, 0.224, 0.225]
REQUIRED_COLS = ["id", "label", "label_id", "img_path", "set", "md5"]


# ---------------------------------------------------------------- 기본 유틸
def resolve(p):
    p = Path(p)
    return p if p.is_absolute() else PROJECT_ROOT / p


def load_config(path):
    with open(resolve(path), encoding="utf-8") as f:
        return json.load(f)


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_text(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def git_commit():
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=PROJECT_ROOT, text=True,
                                       stderr=subprocess.DEVNULL).strip()
    except Exception:
        return None


def env_info():
    import torchvision
    return {"python": platform.python_version(), "torch": torch.__version__,
            "torchvision": torchvision.__version__, "platform": platform.platform()}


def set_seed(seed):
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)
    torch.use_deterministic_algorithms(True, warn_only=True)


def seed_worker(worker_id):
    s = torch.initial_seed() % (2 ** 32)
    random.seed(s)
    np.random.seed(s)


# ---------------------------------------------------------------- 데이터 검증
def load_and_check_meta(cfg):
    """meta CSV를 읽고 학습 전에 반드시 통과해야 하는 검사를 수행 (파이프라인 데이터 검증의 기초)."""
    d = cfg["data"]
    with open(resolve(d["label_map"]), encoding="utf-8") as f:
        label2id = json.load(f)
    class_names = [k for k, _ in sorted(label2id.items(), key=lambda kv: kv[1])]
    df = pd.read_csv(resolve(d["meta_csv"]), keep_default_na=False)

    missing_cols = [c for c in REQUIRED_COLS if c not in df.columns]
    if missing_cols:
        raise ValueError(f"meta에 필수 컬럼이 없습니다: {missing_cols}")

    problems = []
    unknown = set(df["label"]) - set(label2id)
    if unknown:
        problems.append(f"label2id에 없는 라벨: {sorted(unknown)}")
    elif (df["label"].map(label2id) != df["label_id"].astype(int)).any():
        problems.append("label_id가 label2id와 일치하지 않습니다")
    if not set(df["set"]) <= {"train", "val", "test"}:
        problems.append(f"알 수 없는 set 값: {sorted(set(df['set']) - {'train', 'val', 'test'})}")

    remap = d.get("path_remap")
    if remap:
        df["img_path"] = df["img_path"].str.replace(remap["from"], remap["to"], regex=False)
    n_missing = sum(not Path(p).exists() for p in df["img_path"])
    if n_missing:
        problems.append(f"이미지 파일이 없는 행: {n_missing}개")

    sets = {s: df[df["set"] == s] for s in ["train", "val", "test"]}
    for s, part in sets.items():
        if len(part) == 0:
            problems.append(f"{s} 세트가 비어 있습니다")
    for a, b in [("train", "val"), ("train", "test"), ("val", "test")]:
        ov = set(sets[a]["md5"]) & set(sets[b]["md5"])
        if ov:
            problems.append(f"{a}/{b} 사이에 동일 이미지(md5) {len(ov)}개")
        if "blk" in df.columns:
            ovb = set(sets[a]["blk"]) & set(sets[b]["blk"])
            if ovb:
                problems.append(f"{a}/{b} 사이에 같은 블록 그룹 {len(ovb)}개")
    if problems:
        raise ValueError("데이터 검증 실패:\n - " + "\n - ".join(problems))
    return df, class_names


# ---------------------------------------------------------------- 증강
class ChannelGain:
    """조명 색온도 변화 흉내: R, B 채널 이득을 무작위로 바꿈."""

    def __init__(self, lo=0.88, hi=1.12):
        self.lo, self.hi = lo, hi

    def __call__(self, img):
        gr, gb = random.uniform(self.lo, self.hi), random.uniform(self.lo, self.hi)
        r, g, b = img.split()
        return Image.merge("RGB", (r.point(lambda v: min(255, int(v * gr))), g,
                                   b.point(lambda v: min(255, int(v * gb)))))


class RandomJPEG:
    """확률 p로 JPEG 압축 (품질 무작위). 원본 해상도에서 먼저 적용."""

    def __init__(self, q_lo=30, q_hi=95, p=0.5):
        self.q_lo, self.q_hi, self.p = q_lo, q_hi, p

    def __call__(self, img):
        if random.random() > self.p:
            return img
        import io
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=random.randint(self.q_lo, self.q_hi))
        buf.seek(0)
        return Image.open(buf).convert("RGB")


def build_transforms(aug, img_size):
    gray = [T.Grayscale(3)] if aug.get("grayscale") else []
    ops = []
    if aug.get("jpeg"):
        j = aug["jpeg"]
        ops.append(RandomJPEG(j["quality"][0], j["quality"][1], j["p"]))
    ops.append(T.RandomResizedCrop(img_size, scale=tuple(aug.get("random_resized_crop_scale", [0.6, 1.0])),
                                   ratio=(0.9, 1.1)))
    if aug.get("hflip", True):
        ops.append(T.RandomHorizontalFlip())
    if aug.get("vflip", True):
        ops.append(T.RandomVerticalFlip())
    if aug.get("rotation"):
        ops.append(T.RandomRotation(aug["rotation"]))
    if aug.get("color_jitter"):
        ops.append(T.ColorJitter(**aug["color_jitter"]))
    if aug.get("channel_gain"):
        ops.append(ChannelGain(*aug["channel_gain"]))
    if aug.get("blur"):
        b = aug["blur"]
        ops.append(T.RandomApply([T.GaussianBlur(9, sigma=tuple(b["sigma"]))], p=b["p"]))
    ops += gray + [T.ToTensor(), T.Normalize(MEAN, STD)]
    eval_tf = T.Compose([T.Resize((img_size, img_size)), *gray, T.ToTensor(), T.Normalize(MEAN, STD)])
    return T.Compose(ops), eval_tf


# ---------------------------------------------------------------- 데이터셋 / 로더
class SkinDataset(Dataset):
    def __init__(self, df, transform):
        self.paths = df["img_path"].tolist()
        self.labels = df["label_id"].astype(int).tolist()
        self.transform = transform

    def __len__(self):
        return len(self.paths)

    def __getitem__(self, i):
        img = Image.open(self.paths[i]).convert("RGB")
        return self.transform(img), self.labels[i]


def make_loaders(df, cfg, seed, fraction=1.0):
    t = cfg["train"]
    train_tf, eval_tf = build_transforms(cfg["aug"], t["img_size"])
    sets = {s: df[df["set"] == s].reset_index(drop=True) for s in ["train", "val", "test"]}
    if fraction < 1.0:      # 학습 곡선용: 클래스별로 같은 비율만 사용 (val/test는 그대로)
        sets["train"] = (sets["train"].groupby("label", group_keys=False)
                         .sample(frac=fraction, random_state=seed).reset_index(drop=True))
    nw = int(t.get("num_workers", 0))
    base = dict(batch_size=t["batch_size"], num_workers=nw, worker_init_fn=seed_worker,
                pin_memory=torch.cuda.is_available())
    g = torch.Generator()
    g.manual_seed(seed)
    loaders = {
        "train": DataLoader(SkinDataset(sets["train"], train_tf), shuffle=True, generator=g,
                            persistent_workers=nw > 0, **base),
        "val": DataLoader(SkinDataset(sets["val"], eval_tf), shuffle=False, **base),
        "test": DataLoader(SkinDataset(sets["test"], eval_tf), shuffle=False, **base),
    }
    return loaders, sets


# ---------------------------------------------------------------- 모델
def build_model(arch, n_classes, pretrained=True):
    if arch == "mobilenet_v3_small":
        m = models.mobilenet_v3_small(weights=models.MobileNet_V3_Small_Weights.DEFAULT if pretrained else None)
        m.classifier[3] = nn.Linear(m.classifier[3].in_features, n_classes)
    elif arch == "efficientnet_b0":
        m = models.efficientnet_b0(weights=models.EfficientNet_B0_Weights.DEFAULT if pretrained else None)
        m.classifier[1] = nn.Linear(m.classifier[1].in_features, n_classes)
    elif arch == "resnet50":
        m = models.resnet50(weights=models.ResNet50_Weights.DEFAULT if pretrained else None)
        m.fc = nn.Linear(m.fc.in_features, n_classes)
    else:
        raise ValueError(f"지원하지 않는 arch: {arch}")
    return m


# ---------------------------------------------------------------- 평가 유틸
@torch.no_grad()
def predict(model, loader, device, criterion=None):
    model.eval()
    probs, ys, loss_sum, n = [], [], 0.0, 0
    for x, y in loader:
        x, y = x.to(device), y.to(device)
        logits = model(x)
        if criterion is not None:
            loss_sum += criterion(logits, y).item() * x.size(0)
        n += x.size(0)
        probs.append(logits.softmax(1).cpu())
        ys.append(y.cpu())
    loss = loss_sum / n if criterion is not None else None
    return loss, torch.cat(probs).numpy(), torch.cat(ys).numpy()


def wilson_ci(k, n, z=1.96):
    p = k / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return center - half, center + half


def calibrate_threshold(val_probs, val_y, q=5.0, lo=0.30, hi=0.90):
    """val에서 정답으로 예측된 샘플의 최고확률 하위 q%를 '판단 불가' 기준으로 삼음."""
    conf, ok = val_probs.max(1), val_probs.argmax(1) == val_y
    return round(float(np.clip(np.percentile(conf[ok], q), lo, hi)), 2)


def reject_stats(probs, y, thr):
    conf, ok = probs.max(1), probs.argmax(1) == y
    keep = conf >= thr
    return {"coverage": float(keep.mean()),
            "accuracy_on_accepted": float(ok[keep].mean()) if keep.any() else None,
            "errors_total": int((~ok).sum()),
            "errors_rejected": int(((~ok) & (~keep)).sum())}