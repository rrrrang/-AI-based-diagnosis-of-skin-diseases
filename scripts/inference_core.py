"""공용 추론 모듈: 모델 로드, 전처리, 예측, Grad-CAM, 판단 불가 처리."""
import json
import threading
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
from matplotlib import colormaps
from PIL import Image, ImageOps
from torchvision import models, transforms as T

OUT = Path(__file__).resolve().parent.parent / "outputs"          # cam_grid 등 분석 스크립트용
MODEL_DIR = Path(__file__).resolve().parent.parent / "model"      # 릴리스 산출물 위치
CKPT = MODEL_DIR / "best.pt"
THRESH_FILE = MODEL_DIR / "threshold.json"
LABEL_FILE = MODEL_DIR / "label2id.json"
IMG_SIZE = 224
DEFAULT_THRESHOLD = 0.60        # threshold.json이 없을 때 쓰는 임시값 (calibrate_threshold.py로 정함)
MEAN, STD = [0.485, 0.456, 0.406], [0.229, 0.224, 0.225]

# 학습/평가 때와 동일한 전처리
_prep = T.Compose([T.Resize((IMG_SIZE, IMG_SIZE)), T.ToTensor(), T.Normalize(MEAN, STD)])


def load_names():
    with open(LABEL_FILE, encoding="utf-8") as f:
        l2i = json.load(f)
    return [k for k, _ in sorted(l2i.items(), key=lambda kv: kv[1])]


def load_threshold():
    if THRESH_FILE.exists():
        return float(json.load(open(THRESH_FILE, encoding="utf-8"))["threshold"])
    return DEFAULT_THRESHOLD


def to_square(img):
    """휴대폰 사진 회전 정보 반영 -> RGB -> 중앙을 정사각형으로 자름 (학습 이미지가 정사각형이므로)."""
    img = ImageOps.exif_transpose(img).convert("RGB")
    w, h = img.size
    s = min(w, h)
    left, top = (w - s) // 2, (h - s) // 2
    return img.crop((left, top, left + s, top + s))


def decision_text(r, md=True):
    b = "**" if md else ""
    if r["accepted"]:
        return f"예측: {b}{r['pred']}{b} (확신도 {r['conf'] * 100:.1f}%)"
    top = ", ".join(f"{n} {p * 100:.0f}%" for n, p in r["top3"])
    return (f"{b}판단 불가{b}: 최고 확신도 {r['conf'] * 100:.1f}%가 기준({r['threshold'] * 100:.0f}%)보다 낮습니다. "
            f"(후보: {top})")


class Predictor:
    def __init__(self, ckpt=CKPT, threshold=None):
        self.names = load_names()
        m = models.mobilenet_v3_small()
        m.classifier[3] = nn.Linear(m.classifier[3].in_features, len(self.names))
        m.load_state_dict(torch.load(ckpt, map_location="cpu"))
        m.eval()
        for p in m.parameters():
            p.requires_grad_(False)          # 입력 쪽 기울기만 필요 (Grad-CAM)
        self.model = m
        self.threshold = load_threshold() if threshold is None else float(threshold)
        self._acts, self._grads = None, None
        self._lock = threading.Lock()
        m.features[-1].register_forward_hook(self._on_forward)   # Grad-CAM 대상: 마지막 특징 층 (7x7)

    def _on_forward(self, module, inp, out):
        self._acts = out
        if out.requires_grad:
            out.register_hook(lambda g: setattr(self, "_grads", g))

    @torch.no_grad()
    def probs_from_tensor(self, x):
        """이미 전처리된 배치 텐서 -> 확률 (calibrate_threshold.py에서 사용)."""
        return self.model(x).softmax(1)

    def _overlay(self, sq, out_size=448, alpha=0.65):
        if self._grads is None:
            return None
        acts, grads = self._acts.detach(), self._grads
        weights = grads.mean(dim=(2, 3), keepdim=True)
        cam = F.relu((weights * acts).sum(1, keepdim=True))[0, 0].numpy()
        cam = cam - cam.min()
        cam = cam / (cam.max() + 1e-8)
        heat = Image.fromarray((cam * 255).astype(np.uint8)).resize((out_size, out_size), Image.BILINEAR)
        hm = np.asarray(heat, dtype=np.float32) / 255
        color = colormaps["jet"](hm)[..., :3]
        base = np.asarray(sq.resize((out_size, out_size), Image.BICUBIC), dtype=np.float32) / 255
        a = (alpha * hm)[..., None]                  # 주목도가 낮은 곳은 원본이 그대로 보이게
        return Image.fromarray(((1 - a) * base + a * color).__mul__(255).clip(0, 255).astype(np.uint8))

    def predict(self, img, threshold=None, with_cam=True, cam_class=None):
        thr = self.threshold if threshold is None else float(threshold)
        w, h = ImageOps.exif_transpose(img).size
        sq = to_square(img)
        x = _prep(sq).unsqueeze(0)
        overlay, cam_name = None, None
        with self._lock:
            if with_cam:
                self._grads = None
                x.requires_grad_(True)
                with torch.enable_grad():
                    logits = self.model(x)
                    probs = logits.softmax(1)[0].detach()
                    idx = int(probs.argmax()) if cam_class is None else int(cam_class)
                    logits[0, idx].backward()
                overlay, cam_name = self._overlay(sq), self.names[idx]
            else:
                with torch.no_grad():
                    probs = self.model(x).softmax(1)[0]
        p = probs.numpy()
        order = np.argsort(-p)
        warnings = []
        if min(w, h) < IMG_SIZE:
            warnings.append(f"해상도가 낮습니다(짧은 변 {min(w, h)}px). 병변 부위를 가까이서 선명하게 찍으면 더 안정적입니다.")
        if abs(w - h) / max(w, h) > 0.05:
            warnings.append("사진이 정사각형이 아니어서 중앙을 정사각형으로 잘라 분석했습니다.")
        return {
            "names": self.names, "probs": p.tolist(),
            "top3": [(self.names[i], float(p[i])) for i in order[:3]],
            "pred": self.names[order[0]], "conf": float(p[order[0]]),
            "threshold": thr, "accepted": float(p[order[0]]) >= thr,
            "warnings": warnings, "overlay": overlay, "cam_class": cam_name,
        }