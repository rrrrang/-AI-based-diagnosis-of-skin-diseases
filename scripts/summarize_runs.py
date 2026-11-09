import json

import pandas as pd

from skin_lib import resolve

rows = []
for p in sorted(resolve("outputs/runs").glob("*/summary.json")):
    s = json.load(open(p, encoding="utf-8"))
    rows.append({
        "실행": p.parent.name, "학습비율": s["train_fraction"], "학습장수": s["train_n"], "시드수": s["n_seeds"],
        "test 정확도(%)": f"{s['test_acc']['mean'] * 100:.2f} ± {s['test_acc']['std'] * 100:.2f}",
        "macro F1(%)": f"{s['test_macro_f1']['mean'] * 100:.2f} ± {s['test_macro_f1']['std'] * 100:.2f}",
        "최저 클래스 recall(%)": f"{s['min_class_recall']['mean'] * 100:.1f}",
        "판단불가 기준": f"{s['threshold']['mean']:.2f}",
        "test 통과율": f"{s['test_coverage']['mean']:.3f}",
    })
print(pd.DataFrame(rows).sort_values(["학습비율", "실행"]).to_string(index=False) if rows else "결과 없음")