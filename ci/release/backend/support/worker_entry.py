"""Check the packaged model bundle, then launch the unchanged queue worker."""
import argparse
import json
import os
from pathlib import Path
import runpy
import sys
import time

from model_guard import verify_bundle

STATE_PATH = Path("/tmp/skinai_worker_state.json")


def validate_model_roots(argv):
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--mobilenet-root", type=Path, required=True)
    parser.add_argument("--resnet-root", type=Path, required=True)
    parser.add_argument("--yolo-root", type=Path, required=True)
    args, _ = parser.parse_known_args(argv)
    for value, expected in (
        (args.mobilenet_root, Path("/models/mobilenet")),
        (args.resnet_root, Path("/models/resnet50")),
        (args.yolo_root, Path("/models/yolo")),
    ):
        if value.resolve(strict=True) != expected:
            raise ValueError("Worker model roots must use the verified packaged /models bundle")


def main():
    STATE_PATH.unlink(missing_ok=True)
    started_at = time.time()
    verify_bundle(Path("/models"))
    validate_model_roots(sys.argv[1:])
    print("MODEL_BUNDLE_VERIFIED: mobilenet, resnet50, yolo", flush=True)

    # app.worker imports this function after verification. Its first call occurs
    # only after Ensemble has loaded all three models and initialized the DB.
    # Record the actual worker ID so a sibling's heartbeat cannot mark us ready.
    from app import jobs

    heartbeat = jobs.heartbeat

    def record_heartbeat(worker_id):
        result = heartbeat(worker_id)
        state = {"worker_id": worker_id, "started_at": started_at, "pid": os.getpid()}
        temporary = STATE_PATH.with_suffix(".tmp")
        temporary.write_text(json.dumps(state), encoding="utf-8")
        temporary.replace(STATE_PATH)
        return result

    jobs.heartbeat = record_heartbeat
    runpy.run_module("app.worker", run_name="__main__")


if __name__ == "__main__":
    main()
