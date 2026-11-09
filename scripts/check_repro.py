import pandas as pd

from skin_lib import resolve

a = pd.read_csv(resolve("outputs/runs/final_v0_1/seed_42/test_predictions.csv"), encoding="utf-8-sig")
b = pd.read_csv(resolve("outputs/runs/final_v0_1_repro/seed_42/test_predictions.csv"), encoding="utf-8-sig")
m = a.merge(b, on="id", suffixes=("_1", "_2"))
print(f"예측이 달라진 이미지: {(m.pred_1 != m.pred_2).sum()} / {len(m)} | 확신도 최대 차이: {(m.conf_1 - m.conf_2).abs().max():.5f}")