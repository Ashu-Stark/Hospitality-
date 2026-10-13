# HOI platform API + worker portal (/worker) + guest QR pages (/guest)
# Stateless: all data (including photo proof) lives in MongoDB, so no volume is needed.
# Required at runtime: MONGODB_URI (secret), HOI_ENV=production and the settings listed in platform_api/README.md.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY hoi_platform ./hoi_platform

RUN useradd --create-home --uid 10001 hoi
USER hoi
EXPOSE 8100

# /ready pings MongoDB, so an unreachable cluster marks the container unhealthy.
HEALTHCHECK --interval=30s --timeout=5s --retries=3 CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8100/ready').status==200 else 1)"

# One worker: the login/guest rate limiter is in-process (see platform_api/README.md, "Known limits").
CMD ["uvicorn", "hoi_platform.main:app", "--host", "0.0.0.0", "--port", "8100", "--proxy-headers", "--forwarded-allow-ips", "*"]
