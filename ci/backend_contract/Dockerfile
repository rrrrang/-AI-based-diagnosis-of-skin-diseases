FROM python:3.14-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    SKINAI_DB_PATH=/data/backend.sqlite3 \
    SKINAI_PHOTO_DIR=/data/private-photos

WORKDIR /app

COPY requirements-ci.txt ./requirements.txt

RUN python -m pip install --no-cache-dir -r requirements.txt \
    && python -m pip check

COPY --from=backend main.py ./main.py
COPY --from=backend app ./app

RUN useradd --create-home --uid 10001 apiuser \
    && mkdir -p /data/private-photos \
    && chown -R apiuser:apiuser /data

USER apiuser

EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=3s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import json, urllib.request; r = urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=2); assert r.status == 200 and json.load(r).get('status') == 'ok'"]

CMD ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
