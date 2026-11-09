import pandas as pd
from pathlib import Path

OUT = Path(r"D:\skin_project\outputs")
files = {
    "컬러(기본)": "robustness_best_mobilenet_block_ep2.csv",
    "컬러(강건성)": "robustness_best_mobilenet_block_robust.csv",
    "회색조": "robustness_best_mobilenet_block_gray.csv",
}
data = {k: pd.read_csv(OUT / f).set_index("condition") for k, f in files.items() if (OUT / f).exists()}
print("불러온 모델:", list(data))

acc = pd.DataFrame({k: v["accuracy"] for k, v in data.items()}) * 100
print("\n[정확도 %]")
print(acc.round(1).to_string())

print("\n[원본 대비 변화 %p]")
print((acc.sub(acc.loc["원본"], axis=1)).round(1).to_string())

for cond in ["따뜻한 조명", "흐림(blur)"]:
    print(f"\n[{cond}] 클래스별 recall")
    print(pd.DataFrame({k: v.loc[cond].drop("accuracy") for k, v in data.items()}).T.to_string())