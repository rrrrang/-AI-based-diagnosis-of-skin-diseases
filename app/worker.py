import argparse
import hashlib
import json
import logging
import threading
import uuid
from pathlib import Path

from PIL import Image

from app.db import init_db
from app.jobs import LEASE_SECONDS, claim, finish, heartbeat, renew
from app.routers.cases import photo_root
from ensemble.__main__ import Ensemble


def run_job(job, ensemble, versions):
    try:
        with Image.open(photo_root() / job["case_id"] / str(job["photo_index"])) as photo:
            result = ensemble.predict(photo, f'{job["case_id"]}:{job["photo_index"]}', "side_closeup")
        result.update(modelVersions=versions, analyzedPhotoIndex=job["photo_index"])
    except Exception:
        logging.exception("Analysis failed for job %s", job["id"])
        return finish(job, error="inference_failed")
    return finish(job, result=result)


def main():
    parser = argparse.ArgumentParser(description="Process the SQLite analysis queue")
    for name in ("mobilenet-root", "resnet-root", "yolo-root", "thresholds"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    mobile, resnet, yolo = (root.resolve() for root in
                           (args.mobilenet_root, args.resnet_root, args.yolo_root))
    thresholds = json.loads(args.thresholds.read_text(encoding="utf-8-sig"))
    weights = {
        "mobilenet": mobile / "model/best.pt",
        "resnet50": resnet / "models/resnet50_side_best.pth",
        "yolo": yolo / "models/yolo11_detect/side_hard_negative/weights/best.pt",
    }
    versions = {}
    for model, path in weights.items():
        with path.open("rb") as source:
            versions[model] = hashlib.file_digest(source, "sha256").hexdigest()
    ensemble = Ensemble(mobile, resnet, yolo, thresholds)
    init_db()
    worker_id = uuid.uuid4().hex
    stopping = threading.Event()
    active = None

    def maintain_leases():
        while not stopping.wait(LEASE_SECONDS / 4):
            try:
                heartbeat(worker_id)
                job = active
                if job is not None:
                    renew(job)
            except Exception:
                logging.exception("Worker heartbeat failed")

    heartbeat(worker_id)
    thread = threading.Thread(target=maintain_leases, daemon=True)
    thread.start()
    try:
        while True:
            active = claim()
            if active is None:
                stopping.wait(1)
                continue
            run_job(active, ensemble, versions)
            active = None
    finally:
        stopping.set()
        thread.join()


if __name__ == "__main__":
    main()
