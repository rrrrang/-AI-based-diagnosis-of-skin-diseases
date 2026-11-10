"""릴리스 패키지 생성: 선택한 실행/시드의 산출물을 model/, reports/, splits/ 로 모으고 manifest 작성.

"""
import argparse
import json
import shutil

import pandas as pd

from skin_lib import PROJECT_ROOT, env_info, git_commit, resolve, sha256_file


def main():
    ap = argparse.ArgumentParser(description="릴리스 패키지 생성")
    ap.add_argument("--run", default="final_v0_1")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--version", default="v0.1")
    ap.add_argument("--no-splits", action="store_true",
                    help="분할 목록(splits/)과 이미지별 예측(test_predictions.csv)을 패키지에서 제외")
    args = ap.parse_args()
    include_splits = not args.no_splits

    run_dir = resolve("outputs/runs") / args.run
    seed_dir = run_dir / f"seed_{args.seed}"
    need = ["best.pt", "threshold.json", "test_report.json", "config_resolved.json"]
    missing = [n for n in need if not (seed_dir / n).exists()]
    if missing:
        raise SystemExit(f"필요한 파일이 없습니다 ({seed_dir}): {missing}")
    if not (seed_dir / "robustness.csv").exists():
        print("경고: robustness.csv가 없습니다. robustness_test.py를 먼저 실행하세요.")

    model_dir = PROJECT_ROOT / "model"
    rep_dir = PROJECT_ROOT / "reports" / f"seed_{args.seed}"
    split_dir = PROJECT_ROOT / "splits"
    model_dir.mkdir(parents=True, exist_ok=True)
    rep_dir.mkdir(parents=True, exist_ok=True)

    # 모델 산출물
    shutil.copy2(seed_dir / "best.pt", model_dir / "best.pt")
    shutil.copy2(seed_dir / "threshold.json", model_dir / "threshold.json")
    shutil.copy2(resolve("outputs/label2id.json"), model_dir / "label2id.json")

    # 평가 리포트
    names = ["test_report.json", "config_resolved.json", "history.csv", "confusion_test.csv", "robustness.csv"]
    if include_splits:
        names.append("test_predictions.csv")
    for n in names:
        if (seed_dir / n).exists():
            shutil.copy2(seed_dir / n, rep_dir / n)
    for n in ["summary.json", "summary.csv"]:
        if (run_dir / n).exists():
            shutil.copy2(run_dir / n, PROJECT_ROOT / "reports" / n)

    cfg = json.load(open(seed_dir / "config_resolved.json", encoding="utf-8"))

    # 분할 목록: 이미지 경로 없이 id, 라벨, 세트, 해시, 블록만
    if include_splits:
        split_dir.mkdir(parents=True, exist_ok=True)
        meta = pd.read_csv(resolve(cfg["config"]["data"]["meta_csv"]), keep_default_na=False)
        cols = [c for c in ["id", "label", "label_id", "set", "md5", "blk"] if c in meta.columns]
        meta[cols].to_csv(split_dir / "split_block_v1.csv", index=False, encoding="utf-8-sig")
    else:                                    # 이전에 만든 파일이 남아 있으면 제거
        if split_dir.exists():
            shutil.rmtree(split_dir)
        stale = rep_dir / "test_predictions.csv"
        if stale.exists():
            stale.unlink()

    pools = [*model_dir.glob("*")] + ([*split_dir.glob("*")] if include_splits else [])
    files = [p for p in sorted(pools) if p.name != "manifest.json"]
    manifest = {
        "version": args.version, "run": args.run, "seed": args.seed,
        "includes_splits": include_splits,
        "model": cfg["config"]["model"],
        "train_config_sha256": cfg["config_sha256"],
        "meta_csv_sha256": cfg["meta_csv_sha256"],
        "env": env_info(), "git_commit": git_commit(),
        "files": {str(p.relative_to(PROJECT_ROOT)).replace("\\", "/"):
                  {"sha256": sha256_file(p), "bytes": p.stat().st_size} for p in files},
    }
    with open(model_dir / "manifest.json", "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    print(f"릴리스 패키지 생성 완료 (분할 목록 포함: {include_splits})")
    for k, v in manifest["files"].items():
        print(f"  {k}  ({v['bytes']:,} bytes)")


if __name__ == "__main__":
    main()