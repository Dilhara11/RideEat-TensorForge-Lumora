# TensorForge 2.0 API engine: one container, no internet needed at runtime.
#
# Build from the REPOSITORY ROOT (the model bundle lives in training/models/winner):
#   docker build -f app/server/Dockerfile -t tensorforge-api .
# Run (contract command):
#   docker run -p 8000:8000 -e API_KEY=<key> tensorforge-api
# Optional: keep job state across container re-creation with  -v tf-jobs:/app/data
# Optional: let the separately hosted web client (app/client, e.g. on AWS Amplify) call the API:
#   -e CORS_ORIGINS=https://main.<app-id>.amplifyapp.com
#
# The build context is filtered by app/server/Dockerfile.dockerignore (BuildKit), so checkpoints,
# staging models and the dataset are never sent to the daemon.

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# 1) Dependencies first (cached layer while code/model change).
COPY app/server/requirements.txt /app/requirements.txt
RUN pip install -r /app/requirements.txt

# 2) Model bundle, baked into the image. Listing the files explicitly makes the BUILD fail
#    (instead of the container never turning healthy) if any of them is missing.
COPY training/models/winner/model.onnx \
     training/models/winner/inference_config.json \
     training/models/winner/labels.json \
     /app/model/
COPY training/models/winner/tokenizer/ /app/model/tokenizer/

# 3) Engine code.
COPY app/server/tfengine/ /app/tfengine/

# 4) Build-time checks: the app module imports cleanly from the image layout (catches startup crashes
#    at build time), the bundle is complete, labels match the contract, sha256 matches model_version.
RUN python -c "import tfengine.main; from tfengine.config import Settings; Settings.from_env(); \
from tfengine.inference import ModelBundle; b = ModelBundle.open('/app/model'); b.verify_hash(); \
print('import ok | model_version', b.model_version)"

# 5) Unprivileged user; /app/data holds the SQLite job store.
RUN useradd --uid 10001 --create-home --shell /usr/sbin/nologin app \
    && mkdir -p /app/data && chown app:app /app/data
USER app

ENV MODEL_DIR=/app/model \
    DATA_DIR=/app/data \
    ONNX_THREADS=2 \
    LOG_LEVEL=INFO

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=3s --start-period=60s --retries=3 \
  CMD python -c "import sys, urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2).status == 200 else 1)"

# One worker = one model copy (fits 4 GB); job state is in SQLite, so more workers would also be safe.
CMD ["uvicorn", "tfengine.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", \
     "--no-access-log", "--timeout-graceful-shutdown", "10"]
