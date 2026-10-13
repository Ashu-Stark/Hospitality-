# Hospitality Operations Intelligence (HOI) backend image. ALL data is SYNTHETIC.
# Build from the REPO ROOT (the app needs both backend/ and ml/: ml/data + ml/artifacts):
#   docker build -f backend/Dockerfile -t hoi-backend .
#   docker run -p 8000:8000 -e PORT=8000 -e MONGODB_URI=... hoi-backend
# Data lives in MongoDB (MONGODB_URI, database HOI_OPS_DB = hoi_ops). Without MONGODB_URI the app
# falls back to in-memory mongomock (demo only: data is lost on restart).
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app \
    PORT=8000

# LightGBM needs the OpenMP runtime on slim images.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Dependencies first (cached layer): the ML stack and the backend packages, pinned by the lock.
COPY ml/requirements.txt ml/requirements.txt
COPY backend/requirements.txt backend/requirements.txt
COPY backend/requirements-lock.txt backend/requirements-lock.txt
RUN pip install -r ml/requirements.txt -r backend/requirements.txt \
        -c backend/requirements-lock.txt

# Application code + the synthetic data and trained artifacts it loads (never ml/data/internal/,
# excluded by .dockerignore).
COPY ml/ ml/
COPY backend/ backend/

# Non-root user. No local data directory: MongoDB holds the data, and the indexes and the
# employee snapshot are created / seeded at startup when missing.
RUN useradd --create-home --uid 1000 hoi
USER hoi

EXPOSE 8000
# Render injects PORT; backend.serve reads it (default 8000) and binds 0.0.0.0.
CMD ["python", "-m", "backend.serve"]
