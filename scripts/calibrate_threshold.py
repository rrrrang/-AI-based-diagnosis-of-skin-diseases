import json
import os

import numpy as np
import torch

assert os.environ.get("SKIN_GRAY") != "1", "SKIN_GRAY 환경변수를 비우고 실행하세요"

from dataset import get_loaders
from inference_core import Predictor, OUT, THRESH_FILE

P = Predictor(threshold=0.0)
loaders = get_loaders(OUT / "meta_split_block.csv", num_workers=0)


def collect(loader):
    probs, ys = [], []
    for x, y in loader:
        probs.append(P.probs_from_tensor(x))
        ys.append(y)
    p, y = torch.cat(probs).numpy(), torch.cat(ys).numpy()
    return p.max(1), p.argmax(1) == y


stats = {s: collect(loaders[s]) for s in ["val", "test"]}
cv, okv = stats["val"]

print("val 확신도 분포 (정답 예측):", {k: round(float(np.percentile(cv[okv], q)), 3) for k, q in
                                  [("최소", 0), ("5%", 5), ("25%", 25), ("중앙", 50)]})
if (~okv).any():
    print("val 오답 확신도:", np.round(np.sort(cv[~okv]), 3))

thr = round(float(min(max(np.percentile(cv[okv], 5), 0.30), 0.90)), 2)

print("\n기준별 처리율(통과 비율)과 통과한 예측의 정확도")
print(f"{'기준':>5} | {'val 통과율':>9} {'val 정확도':>10} | {'test 통과율':>10} {'test 정확도':>11}")
for t in [0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9]:
    row = []
    for s in ["val", "test"]:
        c, ok = stats[s]
        keep = c >= t
        row += [keep.mean(), ok[keep].mean() if keep.any() else float("nan")]
    print(f"{t:>5.1f} | {row[0]:>9.3f} {row[1]:>10.3f} | {row[2]:>10.3f} {row[3]:>11.3f}")

ct, okt = stats["test"]
print("\ntest 오답의 확신도:", np.round(np.sort(ct[~okt]), 3))
print(f"\n선택한 기준(val 정답 예측 확신도의 5퍼센타일): {thr}")

json.dump({"threshold": thr, "rule": "val 정답 예측 확신도의 5퍼센타일 (범위 0.30~0.90로 제한)",
           "val_n": int(len(cv)), "test_n": int(len(ct))},
          open(THRESH_FILE, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
print("저장:", THRESH_FILE)