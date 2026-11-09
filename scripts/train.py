"""설정 파일 기반 학습: 시드 고정, 다중 시드 실행, 학습 곡선(--train-fraction), 산출물 자동 기록."""
import argparse
import json
import time
from pathlib import Path

import numpy as np
import pandas as pd
import torch
import torch.nn as nn
from sklearn.metrics import classification_report, confusion_matrix, f1_score

from skin_lib import (build_model, calibrate_threshold, env_info, git_commit, load_and_check_meta,
                      load_config, make_loaders, predict, reject_stats, resolve, set_seed,
                      sha256_file, sha256_text, wilson_ci)

OUT_ROOT = resolve("outputs/runs")


def jdump(obj, path):
    def conv(o):
        if isinstance(o, np.integer):
            return int(o)
        if isinstance(o, np.floating):
            return float(o)
        if isinstance(o, np.ndarray):
            return o.tolist()
        if isinstance(o, Path):
            return str(o)
        raise TypeError(type(o))
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2, default=conv)


def train_one_seed(cfg, df, class_names, seed, fraction, run_name, run_dir, device, force):
    seed_dir = run_dir / f"seed_{seed}"
    report_path = seed_dir / "test_report.json"
    if report_path.exists() and not force:
        print(f"[seed {seed}] 이미 완료된 결과가 있어 건너뜁니다 (다시 하려면 --force): {seed_dir}")
        return json.load(open(report_path, encoding="utf-8"))
    seed_dir.mkdir(parents=True, exist_ok=True)

    set_seed(seed)
    t, n_classes = cfg["train"], len(class_names)
    loaders, sets = make_loaders(df, cfg, seed, fraction)
    sizes = {s: len(v) for s, v in sets.items()}
    print(f"[seed {seed}] device={device} | 데이터 {sizes} | 이미지 크기 {t['img_size']}")

    model = build_model(cfg["model"]["arch"], n_classes, cfg["model"].get("pretrained", True)).to(device)
    criterion = nn.CrossEntropyLoss(label_smoothing=t["label_smoothing"])
    optimizer = torch.optim.AdamW(model.parameters(), lr=t["lr"], weight_decay=t["weight_decay"])
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=t["epochs"])

    cfg_text = json.dumps(cfg, sort_keys=True, ensure_ascii=False)
    jdump({"config": cfg, "seed": seed, "train_fraction": fraction, "run_name": run_name, "device": device,
           "class_names": class_names, "sizes": sizes, "env": env_info(), "git_commit": git_commit(),
           "config_sha256": sha256_text(cfg_text),
           "meta_csv_sha256": sha256_file(resolve(cfg["data"]["meta_csv"]))},
          seed_dir / "config_resolved.json")

    best_key, best_epoch, bad, history = (-1.0, -1e9), 0, 0, []
    t_start = time.time()
    for ep in range(1, t["epochs"] + 1):
        t0 = time.time()
        model.train()
        loss_sum, tr_pred, tr_y = 0.0, [], []
        for x, y in loaders["train"]:
            x, y = x.to(device), y.to(device)
            logits = model(x)
            loss = criterion(logits, y)
            optimizer.zero_grad(set_to_none=True)
            loss.backward()
            optimizer.step()
            loss_sum += loss.item() * x.size(0)
            tr_pred.append(logits.argmax(1).cpu())
            tr_y.append(y.cpu())
        scheduler.step()
        tr_loss = loss_sum / sizes["train"]
        tr_f1 = f1_score(torch.cat(tr_y).numpy(), torch.cat(tr_pred).numpy(), average="macro")
        va_loss, va_p, va_y = predict(model, loaders["val"], device, criterion)
        va_f1 = f1_score(va_y, va_p.argmax(1), average="macro")
        print(f"  [{ep:02d}/{t['epochs']}] train loss {tr_loss:.3f} f1 {tr_f1:.3f} | "
              f"val loss {va_loss:.3f} f1 {va_f1:.3f} | {(time.time() - t0) / 60:.1f}분")
        history.append({"epoch": ep, "tr_loss": tr_loss, "tr_f1": tr_f1, "va_loss": va_loss, "va_f1": va_f1})
        pd.DataFrame(history).to_csv(seed_dir / "history.csv", index=False)

        key = (round(va_f1, 3), -va_loss)       # val F1이 같으면(포화) val loss가 낮은 쪽을 선택
        if key > best_key:
            best_key, best_epoch, bad = key, ep, 0
            torch.save(model.state_dict(), seed_dir / "best.pt")
        else:
            bad += 1
            if bad >= t["patience"]:
                print("  early stopping")
                break

    # ---- 최종 평가 (test는 여기서 한 번만)
    model.load_state_dict(torch.load(seed_dir / "best.pt", map_location=device))
    va_loss, va_p, va_y = predict(model, loaders["val"], device, criterion)
    te_loss, te_p, te_y = predict(model, loaders["test"], device, criterion)
    te_pred = te_p.argmax(1)
    k, n = int((te_pred == te_y).sum()), len(te_y)
    ci_lo, ci_hi = wilson_ci(k, n)
    rep = classification_report(te_y, te_pred, labels=list(range(n_classes)), target_names=class_names,
                                output_dict=True, zero_division=0)
    per_class = {c: {"precision": rep[c]["precision"], "recall": rep[c]["recall"],
                     "f1": rep[c]["f1-score"], "support": int(rep[c]["support"])} for c in class_names}

    thc = cfg.get("threshold", {})
    thr = calibrate_threshold(va_p, va_y, thc.get("percentile", 5), thc.get("min", 0.30), thc.get("max", 0.90))
    jdump({"threshold": thr, "rule": f"val 정답 예측 확신도의 {thc.get('percentile', 5)}퍼센타일",
           "checkpoint": "best.pt"}, seed_dir / "threshold.json")

    cm = pd.DataFrame(confusion_matrix(te_y, te_pred, labels=list(range(n_classes))),
                      index=class_names, columns=class_names)
    cm.to_csv(seed_dir / "confusion_test.csv", encoding="utf-8-sig")
    pd.DataFrame({"id": sets["test"]["id"], "label": sets["test"]["label"],
                  "pred": [class_names[i] for i in te_pred], "conf": te_p.max(1)}
                 ).to_csv(seed_dir / "test_predictions.csv", index=False, encoding="utf-8-sig")

    report = {
        "run": run_name, "seed": seed, "train_fraction": fraction, "sizes": sizes,
        "best_epoch": best_epoch, "epochs_run": len(history),
        "train_minutes": round((time.time() - t_start) / 60, 1),
        "val": {"accuracy": float((va_p.argmax(1) == va_y).mean()),
                "macro_f1": float(f1_score(va_y, va_p.argmax(1), average="macro"))},
        "test": {"accuracy": k / n, "ci95": [ci_lo, ci_hi], "errors": n - k,
                 "macro_f1": float(f1_score(te_y, te_pred, average="macro")), "per_class": per_class},
        "threshold": thr,
        "reject_val": reject_stats(va_p, va_y, thr),
        "reject_test": reject_stats(te_p, te_y, thr),
    }
    jdump(report, report_path)
    print(f"[seed {seed}] TEST 정확도 {k / n:.4f} ({k}/{n}, 95% CI {ci_lo:.3f}~{ci_hi:.3f}) | "
          f"macro F1 {report['test']['macro_f1']:.4f} | best epoch {best_epoch} | 기준 {thr}")
    return report


def aggregate(reports, class_names, run_name, fraction, run_dir):
    def ms(vals):
        v = np.array(vals, dtype=float)
        return {"mean": float(v.mean()), "std": float(v.std(ddof=1)) if len(v) > 1 else 0.0,
                "values": [float(x) for x in v]}

    summary = {
        "run": run_name, "train_fraction": fraction, "n_seeds": len(reports),
        "seeds": [r["seed"] for r in reports], "train_n": reports[0]["sizes"]["train"],
        "test_acc": ms([r["test"]["accuracy"] for r in reports]),
        "test_macro_f1": ms([r["test"]["macro_f1"] for r in reports]),
        "min_class_recall": ms([min(v["recall"] for v in r["test"]["per_class"].values()) for r in reports]),
        "per_class_recall": {c: ms([r["test"]["per_class"][c]["recall"] for r in reports]) for c in class_names},
        "threshold": ms([r["threshold"] for r in reports]),
        "test_coverage": ms([r["reject_test"]["coverage"] for r in reports]),
    }
    jdump(summary, run_dir / "summary.json")
    rows = [{"seed": r["seed"], "best_epoch": r["best_epoch"], "test_acc": r["test"]["accuracy"],
             "macro_f1": r["test"]["macro_f1"], "threshold": r["threshold"],
             **{f"recall_{c}": r["test"]["per_class"][c]["recall"] for c in class_names}} for r in reports]
    pd.DataFrame(rows).to_csv(run_dir / "summary.csv", index=False, encoding="utf-8-sig")

    print("\n" + "=" * 70)
    print(f"실행 '{run_name}' 요약 (시드 {summary['seeds']}, 학습 {summary['train_n']}장)")
    for name in ["test_acc", "test_macro_f1", "min_class_recall"]:
        s = summary[name]
        print(f"  {name:>17}: {s['mean'] * 100:.2f} ± {s['std'] * 100:.2f}   (시드별 {[round(x * 100, 2) for x in s['values']]})")
    print("  클래스별 recall(평균): " + ", ".join(f"{c} {summary['per_class_recall'][c]['mean']:.3f}" for c in class_names))
    print("=" * 70)


def main():
    ap = argparse.ArgumentParser(description="설정 기반 학습 (다중 시드, 학습 곡선 지원)")
    ap.add_argument("--config", required=True)
    ap.add_argument("--seeds", type=int, nargs="+", default=[42])
    ap.add_argument("--train-fraction", type=float, default=1.0, help="학습 데이터 사용 비율 (학습 곡선용)")
    ap.add_argument("--epochs", type=int, help="설정의 epochs를 덮어씀 (스모크 테스트용)")
    ap.add_argument("--run-name")
    ap.add_argument("--device", default="auto")
    ap.add_argument("--force", action="store_true", help="이미 완료된 시드도 다시 학습")
    args = ap.parse_args()

    cfg = load_config(args.config)
    if args.epochs:
        cfg["train"]["epochs"] = args.epochs
    frac = args.train_fraction
    run_name = args.run_name or (cfg["name"] + (f"_frac{frac:g}" if frac < 1.0 else "")
                                 + (f"_ep{args.epochs}" if args.epochs else ""))
    device = ("cuda" if torch.cuda.is_available() else "cpu") if args.device == "auto" else args.device
    run_dir = OUT_ROOT / run_name
    run_dir.mkdir(parents=True, exist_ok=True)

    df, class_names = load_and_check_meta(cfg)           # 검증 실패 시 여기서 중단
    print("데이터 검증 통과:")
    print(pd.crosstab(df["label"], df["set"])[["train", "val", "test"]].to_string())
    print(f"\n실행 이름: {run_name} | 시드: {args.seeds} | 학습 비율: {frac:g}\n")

    reports = [train_one_seed(cfg, df, class_names, s, frac, run_name, run_dir, device, args.force)
               for s in args.seeds]
    aggregate(reports, class_names, run_name, frac, run_dir)
    print(f"산출물 위치: {run_dir}")


if __name__ == "__main__":      # Windows에서 DataLoader worker를 쓰려면 필요
    main()