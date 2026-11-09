"""강건성 시험: 테스트 이미지에 인위적 교란을 가하고 정확도와 클래스별 recall을 측정.

사용 예)
  python scripts/robustness_test.py --ckpt runs/final_v0_1/seed_42/best.pt
  python scripts/robustness_test.py --ckpt best_mobilenet_block_gray.pt --gray    # 구버전 체크포인트 (설정 파일 없음)
"""
import argparse
import io
import json
from pathlib import Path

import numpy as np
import pandas as pd
import torch
import torchvision.transforms.functional as TF
from PIL import Image
from sklearn.metrics import accuracy_score, confusion_matrix
from torch.utils.data import DataLoader, Dataset
from torchvision import transforms as T

from skin_lib import MEAN, STD, build_model, resolve

OUT = resolve("outputs")


# ---------------------------------------------------------------- 교란 함수 (PIL 이미지 -> PIL 이미지)
def warm(img):      # 따뜻한 조명 (R 증가, B 감소)
    r, g, b = img.split()
    return Image.merge("RGB", (r.point(lambda v: min(255, int(v * 1.15))), g,
                               b.point(lambda v: int(v * 0.85))))


def cool(img):      # 차가운 조명 (R 감소, B 증가)
    r, g, b = img.split()
    return Image.merge("RGB", (r.point(lambda v: int(v * 0.85)), g,
                               b.point(lambda v: min(255, int(v * 1.15)))))


def green_tint(img):    # 증강에 없던 방향의 색 치우침
    r, g, b = img.split()
    return Image.merge("RGB", (r, g.point(lambda v: min(255, int(v * 1.15))), b))


def center_crop70(img):     # 중앙 70%만 남김 (이후 Resize가 입력 크기로 되돌림)
    w, h = img.size
    return TF.center_crop(img, [int(h * 0.7), int(w * 0.7)])


def border_only(img):       # 중앙 60%x60%를 회색으로 가리고 가장자리만 남김
    w, h = img.size
    out = img.copy()
    out.paste((128, 128, 128), (int(w * 0.2), int(h * 0.2), int(w * 0.8), int(h * 0.8)))
    return out


def jpeg_q(img, q):         # JPEG 압축 (품질 q)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=q)
    buf.seek(0)
    return Image.open(buf).convert("RGB")


def gauss_noise(img, sigma=12):
    a = np.asarray(img, dtype=np.float32)
    rng = np.random.default_rng(int(a[::64, ::64].sum()) % (2 ** 32))   # 이미지 내용으로 시드 -> 실행 순서와 무관하게 재현
    a = a + rng.normal(0, sigma, a.shape)
    return Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))


def low_res(img):           # 해상도 저하 (128px로 줄였다가 복원)
    w, h = img.size
    return img.resize((128, 128), Image.BILINEAR).resize((w, h), Image.BILINEAR)


CONDS = {
    "원본": lambda im: im,
    "어둡게(x0.7)": lambda im: TF.adjust_brightness(im, 0.7),
    "밝게(x1.3)": lambda im: TF.adjust_brightness(im, 1.3),
    "채도 낮춤(x0.6)": lambda im: TF.adjust_saturation(im, 0.6),
    "채도 높임(x1.4)": lambda im: TF.adjust_saturation(im, 1.4),
    "따뜻한 조명": warm,
    "차가운 조명": cool,
    "흐림(blur)": lambda im: TF.gaussian_blur(im, kernel_size=9, sigma=3),
    "중앙 70% 크롭": center_crop70,
    "중앙 가림(가장자리만)": border_only,
    "JPEG 품질40": lambda im: jpeg_q(im, 40),
    "JPEG 품질20": lambda im: jpeg_q(im, 20),
    "JPEG 품질10": lambda im: jpeg_q(im, 10),
    "가우시안 노이즈": gauss_noise,
    "해상도 저하(128px)": low_res,
    "초록 색조": green_tint,
    "색상 이동(hue +0.05)": lambda im: TF.adjust_hue(im, 0.05),
    "감마 0.6(밝게)": lambda im: TF.adjust_gamma(im, 0.6),
    "감마 1.6(어둡게)": lambda im: TF.adjust_gamma(im, 1.6),
}


class PerturbedDataset(Dataset):
    def __init__(self, df, fn, base):
        self.paths = df["img_path"].tolist()
        self.labels = df["label_id"].astype(int).tolist()
        self.fn, self.base = fn, base

    def __len__(self):
        return len(self.paths)

    def __getitem__(self, i):
        img = Image.open(self.paths[i]).convert("RGB")
        return self.base(self.fn(img)), self.labels[i]


def main():
    ap = argparse.ArgumentParser(description="강건성 시험")
    ap.add_argument("--ckpt", default="runs/final_v0_1/seed_42/best.pt",
                    help="outputs 기준 상대 경로 또는 절대 경로")
    ap.add_argument("--arch", help="모델 구조 (설정 파일이 없을 때만 필요, 기본 mobilenet_v3_small)")
    ap.add_argument("--gray", action="store_true", help="회색조로 학습한 체크포인트 (설정 파일이 없을 때만 필요)")
    ap.add_argument("--meta", help="평가용 meta CSV (기본: 설정 파일의 meta 또는 outputs/meta_split_block.csv)")
    args = ap.parse_args()

    ck = Path(args.ckpt)
    ck = ck if ck.is_absolute() else OUT / ck
    if not ck.exists():
        raise SystemExit(f"체크포인트가 없습니다: {ck}")

    cfg_path = ck.with_name("config_resolved.json")
    cfg = json.load(open(cfg_path, encoding="utf-8"))["config"] if cfg_path.exists() else None
    arch = args.arch or (cfg["model"]["arch"] if cfg else "mobilenet_v3_small")
    gray = args.gray or bool(cfg and cfg["aug"].get("grayscale"))
    img_size = cfg["train"]["img_size"] if cfg else 224
    meta_csv = resolve(args.meta) if args.meta else resolve(cfg["data"]["meta_csv"] if cfg else "outputs/meta_split_block.csv")
    label_map = resolve(cfg["data"]["label_map"] if cfg else "outputs/label2id.json")

    names = [k for k, _ in sorted(json.load(open(label_map, encoding="utf-8")).items(), key=lambda kv: kv[1])]
    te = pd.read_csv(meta_csv, keep_default_na=False).query("set == 'test'").reset_index(drop=True)
    remap = cfg["data"].get("path_remap") if cfg else None
    if remap:
        te["img_path"] = te["img_path"].str.replace(remap["from"], remap["to"], regex=False)

    model = build_model(arch, len(names), pretrained=False)
    model.load_state_dict(torch.load(ck, map_location="cpu"))
    model.eval()

    base = T.Compose([T.Resize((img_size, img_size)), *([T.Grayscale(3)] if gray else []),
                      T.ToTensor(), T.Normalize(MEAN, STD)])

    rep_path = ck.with_name("test_report.json")
    expected = json.load(open(rep_path, encoding="utf-8"))["test"]["accuracy"] if rep_path.exists() else None
    out_csv = OUT / f"robustness_{ck.stem}.csv" if ck.parent == OUT else ck.with_name("robustness.csv")

    print(f"체크포인트: {ck}\narch: {arch} | 회색조: {gray} | 이미지 크기: {img_size} | test: {len(te)}장\n")

    rows = []
    for name, fn in CONDS.items():
        preds, ys = [], []
        with torch.no_grad():
            # num_workers=0: lambda 함수는 Windows 멀티프로세싱에서 전달되지 않으므로 0으로 고정
            for x, y in DataLoader(PerturbedDataset(te, fn, base), batch_size=32, num_workers=0):
                preds += model(x).argmax(1).tolist()
                ys += y.tolist()
        cm = confusion_matrix(ys, preds, labels=list(range(len(names))))
        recall = {n: round(float(cm[i, i] / max(cm[i].sum(), 1)), 2) for i, n in enumerate(names)}
        acc = accuracy_score(ys, preds)
        print(f"{name}: {acc:.4f} | recall {recall}")
        if name == "원본" and expected is not None:
            if abs(acc - expected) > 0.003:
                print(f"  !! 경고: test_report.json의 정확도({expected:.4f})와 다릅니다. "
                      f"체크포인트와 설정(회색조/이미지 크기)을 확인하세요.")
            else:
                print("  (test_report.json과 일치: 평가 설정 정상)")
        rows.append({"condition": name, "accuracy": round(acc, 4), **recall})
        pd.DataFrame(rows).to_csv(out_csv, index=False, encoding="utf-8-sig")   # 조건마다 저장

    res = pd.DataFrame(rows)
    base_acc = float(res.loc[res["condition"] == "원본", "accuracy"].iloc[0])
    worst = res[res["condition"] != "원본"].nsmallest(5, "accuracy")[["condition", "accuracy"]].copy()
    worst["원본 대비(%p)"] = ((worst["accuracy"] - base_acc) * 100).round(1)
    print("\n정확도가 낮은 조건 TOP5")
    print(worst.to_string(index=False))
    print(f"\n저장: {out_csv}")


if __name__ == "__main__":
    main()