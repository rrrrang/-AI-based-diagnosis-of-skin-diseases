"""크롭·위치 민감도 시험 (+ 앙상블/TTA 비교).

사용 예)
  python scripts/crop_sensitivity.py --ckpt runs/final_v0_1/seed_42/best.pt
  python scripts/crop_sensitivity.py --ckpt runs/final_v0_1/seed_42/best.pt --save-crops
  python scripts/crop_sensitivity.py --ckpt runs/final_v0_1/seed_42/best.pt runs/final_v0_1/seed_43/best.pt runs/final_v0_1/seed_44/best.pt --tta --tag ens3_tta
  python scripts/crop_sensitivity.py --ckpt <체크포인트> --split val          # 개발 중 판단은 val로
"""
import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
import torch
from PIL import Image, ImageOps
from torch.utils.data import DataLoader, Dataset
from torchvision import transforms as T

from skin_lib import MEAN, STD, build_model, resolve

OUT = resolve("outputs")


def make_crop(scale, anchor):
    def fn(im):
        if scale >= 1.0:
            return im
        w, h = im.size
        s = int(round(min(w, h) * scale ** 0.5))          # 면적 비율 scale -> 한 변 비율 sqrt(scale)
        x, y = {"center": ((w - s) // 2, (h - s) // 2), "tl": (0, 0), "br": (w - s, h - s)}[anchor]
        return im.crop((x, y, x + s, y + s))
    return fn


class CropDS(Dataset):
    def __init__(self, df, crop, base, views, save_dir=None):
        self.paths = df["img_path"].tolist()
        self.labels = df["label_id"].astype(int).tolist()
        self.crop, self.base, self.views = crop, base, views
        self.save_dir = save_dir
        if self.save_dir is not None:
            self.save_dir.mkdir(parents=True, exist_ok=True)

    def __len__(self):
        return len(self.paths)

    def __getitem__(self, i):
        path = Path(self.paths[i])
        with Image.open(path) as source:
            img = self.crop(source.convert("RGB"))
        if self.save_dir is not None:
            img.save(self.save_dir / f"{i:05d}_{path.stem}.png")
        return torch.stack([self.base(v(img)) for v in self.views]), self.labels[i]


@torch.no_grad()
def run(models, df, crop, base, views, bs=16, save_dir=None):
    probs, ys = [], []
    for x, y in DataLoader(CropDS(df, crop, base, views, save_dir), batch_size=bs, num_workers=0):
        b, v = x.shape[:2]
        x = x.view(b * v, *x.shape[2:])
        p = torch.stack([m(x).softmax(1) for m in models]).mean(0)      # 앙상블 평균
        probs.append(p.view(b, v, -1).mean(1))                          # TTA 평균
        ys.append(y)
    return torch.cat(probs).numpy(), torch.cat(ys).numpy()


def main():
    ap = argparse.ArgumentParser(description="크롭·위치 민감도 시험")
    ap.add_argument("--ckpt", nargs="+", required=True, help="outputs 기준 상대 경로 (여러 개면 앙상블)")
    ap.add_argument("--tta", action="store_true", help="좌우·상하 뒤집기 평균")
    ap.add_argument("--split", default="test", choices=["test", "val"])
    ap.add_argument("--n", type=int, default=50, help="클래스당 평가 이미지 수 (test는 최대 98)")
    ap.add_argument("--tag", default=None)
    ap.add_argument("--save-crops", action="store_true", help="평가용 크롭을 조건별 PNG로 저장")
    args = ap.parse_args()

    cks = [Path(c) if Path(c).is_absolute() else OUT / c for c in args.ckpt]
    cfg_path = cks[0].with_name("config_resolved.json")
    if not cfg_path.exists():
        raise SystemExit("첫 번째 체크포인트 옆에 config_resolved.json이 있어야 합니다")
    cfg = json.load(open(cfg_path, encoding="utf-8"))["config"]
    names = [k for k, _ in sorted(json.load(open(resolve(cfg["data"]["label_map"]), encoding="utf-8")).items(),
                                  key=lambda kv: kv[1])]
    size, gray = cfg["train"]["img_size"], bool(cfg["aug"].get("grayscale"))
    base = T.Compose([T.Resize((size, size)), *([T.Grayscale(3)] if gray else []),
                      T.ToTensor(), T.Normalize(MEAN, STD)])
    views = [lambda im: im] + ([ImageOps.mirror, ImageOps.flip] if args.tta else [])

    models = []
    for ck in cks:
        m = build_model(cfg["model"]["arch"], len(names), pretrained=False)
        m.load_state_dict(torch.load(ck, map_location="cpu"))
        models.append(m.eval())

    meta = pd.read_csv(resolve(cfg["data"]["meta_csv"]), keep_default_na=False)
    remap = cfg["data"].get("path_remap")
    if remap:
        meta["img_path"] = meta["img_path"].str.replace(remap["from"], remap["to"], regex=False)

    def pick(split, n, rs):
        return meta[meta["set"] == split].groupby("label", group_keys=False).sample(n, random_state=rs).reset_index(drop=True)

    val = pick("val", 100, 0)                                          # 판단 불가 기준은 같은 예측기로 val에서 새로 보정
    ev = pick(args.split, args.n, 0 if args.split == "test" else 1)
    full = make_crop(1.0, "center")
    vp, vy = run(models, val, full, base, views)
    conf_v, ok_v = vp.max(1), vp.argmax(1) == vy
    thr = float(np.clip(np.percentile(conf_v[ok_v], 5), 0.30, 0.90))

    tag = args.tag or ("ens%d" % len(models) if len(models) > 1 else "single") + ("_tta" if args.tta else "")
    crop_dir = OUT / f"crops_{tag}" / args.split
    conds = [("전체(기준)", full, None)]
    for s in (0.7, 0.5, 0.35):
        for a in ("center", "tl", "br"):
            pct = int(s * 100)
            conds.append((f"면적 {pct}% {a}", make_crop(s, a), f"{pct}pct_{a}"))

    rows, base_pred, base_keep = [], None, None
    for name, fn, folder in conds:
        save_dir = crop_dir / folder if args.save_crops and folder is not None else None
        p, y = run(models, ev, fn, base, views, save_dir=save_dir)
        pred, conf = p.argmax(1), p.max(1)
        ok, keep = pred == y, conf >= thr
        if base_pred is None:
            base_pred, base_keep = pred, keep
        rows.append({"조건": name, "정확도": ok.mean(), "통과율": keep.mean(),
                     "통과예측정확도": ok[keep].mean() if keep.any() else np.nan,
                     "평균확신도": conf.mean(),
                     "전체이미지와_예측일치": (pred == base_pred).mean(),
                     "통과판정_변경": (keep != base_keep).mean()})
        print(f"{name}: 정확도 {ok.mean():.3f} | 통과율 {keep.mean():.3f} | 예측일치 {(pred == base_pred).mean():.3f}")

    df = pd.DataFrame(rows)
    out_csv = OUT / f"crop_sensitivity_{tag}.csv"
    df.round(3).to_csv(out_csv, index=False, encoding="utf-8-sig")
    print(f"\n모델 {len(models)}개 | 뷰 {len(views)}개 | 평가 {args.split} {len(ev)}장 | 판단 불가 기준 {thr:.2f}")
    print(df.round(3).to_string(index=False))
    print("\n저장:", out_csv)
    if args.save_crops:
        print("크롭 이미지 저장:", crop_dir)


if __name__ == "__main__":
    main()
