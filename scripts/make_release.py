"""릴리스 패키지 생성: 선택한 실행/시드의 산출물을 model/, reports/, splits/ 로 복사하고 manifest 작성."""
import argparse
import json
import shutil

import pandas as pd

from skin_lib import PROJECT_ROOT, env_info, git_commit, resolve, sha256_file


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", default="final_v0_1")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--version", default="v0.1")
    args = ap.parse_args()

    run_dir = resolve("outputs/runs") / args.run
    seed_dir = run_dir / f"seed_{args.seed}"
    need = ["best.pt", "threshold.json", "test_report.json", "config_resolved.json"]
    missing = [n for n in need if not (seed_dir / n).exists()]
    if missing:
        raise SystemExit(f"필요한 파일이 없습니다 ({seed_dir}): {missing}")

    model_dir = PROJECT_ROOT / "model"
    rep_dir = PROJECT_ROOT / "reports" / f"seed_{args.seed}"
    split_dir = PROJECT_ROOT / "splits"
    for d in (model_dir, rep_dir, split_dir):
        d.mkdir(parents=True, exist_ok=True)

    shutil.copy2(seed_dir / "best.pt", model_dir / "best.pt")
    shutil.copy2(seed_dir / "threshold.json", model_dir / "threshold.json")
    shutil.copy2(resolve("outputs/label2id.json"), model_dir / "label2id.json")
    for n in ["test_report.json", "config_resolved.json", "history.csv", "confusion_test.csv",
              "test_predictions.csv", "robustness.csv"]:
        if (seed_dir / n).exists():
            shutil.copy2(seed_dir / n, rep_dir / n)
    for n in ["summary.json", "summary.csv"]:
        if (run_dir / n).exists():
            shutil.copy2(run_dir / n, PROJECT_ROOT / "reports" / n)

    cfg = json.load(open(seed_dir / "config_resolved.json", encoding="utf-8"))
    meta = pd.read_csv(resolve(cfg["config"]["data"]["meta_csv"]), keep_default_na=False)
    cols = [c for c in ["id", "label", "label_id", "set", "md5", "blk"] if c in meta.columns]
    meta[cols].to_csv(split_dir / "split_block_v1.csv", index=False, encoding="utf-8-sig")

    files = [p for p in sorted([*model_dir.glob("*"), *split_dir.glob("*")]) if p.name != "manifest.json"]
    manifest = {
        "version": args.version, "run": args.run, "seed": args.seed,
        "model": cfg["config"]["model"], "train_config_sha256": cfg["config_sha256"],
        "meta_csv_sha256": cfg["meta_csv_sha256"], "env": env_info(), "git_commit": git_commit(),
        "files": {str(p.relative_to(PROJECT_ROOT)).replace("\\", "/"):
                  {"sha256": sha256_file(p), "bytes": p.stat().st_size} for p in files},
    }
    with open(model_dir / "manifest.json", "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    print("릴리스 패키지 생성 완료:", model_dir)
    for k, v in manifest["files"].items():
        print(f"  {k}  ({v['bytes']:,} bytes)")


if __name__ == "__main__":
    main()