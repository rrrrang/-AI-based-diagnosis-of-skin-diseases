# Build from the repository root; pass the verified local bundle as named context "models".
FROM python:3.12-slim-bookworm@sha256:935c3c5b12357a7e10caa9c1e6ca5692344d97cf229832ef584be2cec9fc03df AS api
ENV PYTHONUTF8=1 PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/srv HOME=/tmp \
    SKINAI_DB_PATH=/data/db/backend.sqlite3 SKINAI_PHOTO_DIR=/data/photos
WORKDIR /srv
RUN groupadd --gid 10001 skinai \
    && useradd --uid 10001 --gid 10001 --no-create-home --home-dir /tmp --shell /usr/sbin/nologin skinai \
    && mkdir -p /data/db /data/photos \
    && chown -R 10001:10001 /data
COPY ci/release/backend/requirements-api.lock /srv/support/requirements-api.lock
RUN python -m pip install --no-cache-dir --no-deps -r /srv/support/requirements-api.lock \
    && python -m pip check
COPY main.py /srv/main.py
COPY app/ /srv/app/
COPY ensemble/ /srv/ensemble/
COPY ci/release/backend/support/api_health.py /srv/support/api_health.py
USER 10001:10001
EXPOSE 8000
HEALTHCHECK --interval=5s --timeout=4s --start-period=10s --retries=12 \
    CMD ["python", "/srv/support/api_health.py"]
CMD ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]

FROM api AS worker
USER root
ENV OMP_NUM_THREADS=2 MKL_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2 \
    MPLCONFIGDIR=/tmp/matplotlib YOLO_CONFIG_DIR=/tmp/ultralytics \
    YOLO_AUTOINSTALL=false YOLO_OFFLINE=true
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*
COPY ci/release/backend/requirements-worker.lock /srv/support/requirements-worker.lock
RUN python -m pip install --no-cache-dir --no-deps torch==2.8.0+cpu torchvision==0.23.0+cpu \
        --index-url https://download.pytorch.org/whl/cpu \
    && python -m pip install --no-cache-dir --no-deps -r /srv/support/requirements-worker.lock \
    && python -m pip check
COPY ci/release/backend/support/model_guard.py ci/release/backend/support/worker_entry.py ci/release/backend/support/worker_health.py /srv/support/
COPY ci/release/backend/model-lock.json /srv/model-lock.json
COPY --from=models . /models/
RUN python /srv/support/model_guard.py --models-root /models
USER 10001:10001
HEALTHCHECK --interval=5s --timeout=4s --start-period=60s --retries=18 \
    CMD ["python", "/srv/support/worker_health.py"]
CMD ["python", "/srv/support/worker_entry.py", "--mobilenet-root", "/models/mobilenet", "--resnet-root", "/models/resnet50", "--yolo-root", "/models/yolo", "--thresholds", "/srv/ensemble/thresholds.example.json"]
