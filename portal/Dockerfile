# Uttarakhand Tourism & Hospitality Portal (concept) - API + static web app
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY hoi_portal ./hoi_portal

RUN useradd --create-home --uid 10001 portal
USER portal
EXPOSE 8200

HEALTHCHECK --interval=30s --timeout=5s --retries=3 CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8200/ready').status==200 else 1)"

# One worker: the in-process rate limiter and crowd cache assume a single process (see README, "Scaling").
CMD ["uvicorn", "hoi_portal.main:app", "--host", "0.0.0.0", "--port", "8200", "--proxy-headers", "--forwarded-allow-ips", "*"]
