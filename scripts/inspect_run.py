import json
import sys

import pandas as pd

from skin_lib import resolve

run = sys.argv[1] if len(sys.argv) > 1 else "final_v0_1"
run_dir = resolve("outputs/runs") / run
errs = {}
for sd in sorted(run_dir.glob("seed_*")):
    rep_p = sd / "test_report.json"
    if not rep_p.exists():
        continue
    rep = json.load(open(rep_p, encoding="utf-8"))
    rj, rv = rep["reject_test"], rep["reject_val"]
    acc_acc = rj["accuracy_on_accepted"]
    print(f"{sd.name}: 기준 {rep['threshold']} | val 통과율 {rv['coverage']:.3f} | test 통과율 {rj['coverage']:.3f} | "
          f"통과 예측 정확도 {round(acc_acc, 4) if acc_acc is not None else None} | "
          f"오답 {rj['errors_total']}장 중 {rj['errors_rejected']}장이 판단 불가")
    p = pd.read_csv(sd / "test_predictions.csv", encoding="utf-8-sig")
    e = p[p["label"] != p["pred"]]
    errs[sd.name] = e
    print(e[["id", "label", "pred", "conf"]].round(3).to_string(index=False), "\n")

if len(errs) > 1:
    common = set.intersection(*[set(e["id"]) for e in errs.values()])
    union = set.union(*[set(e["id"]) for e in errs.values()])
    print("모든 시드에서 공통으로 틀린 이미지:", sorted(common) or "없음")
    print(f"한 번이라도 틀린 이미지 {len(union)}장 | 시드별 오답 수 {[len(e) for e in errs.values()]}")