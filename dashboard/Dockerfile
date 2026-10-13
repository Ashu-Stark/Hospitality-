# HOI dashboard (Streamlit). Talks to the platform API over HTTP (PLATFORM_API_URL) and the ML API (API_BASE_URL).
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 USE_MOCKS=true
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN useradd --create-home --uid 10001 hoi && chown -R hoi:hoi /app
USER hoi
EXPOSE 8501

HEALTHCHECK --interval=30s --timeout=5s --retries=3 CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8501/_stcore/health').status==200 else 1)"

CMD ["streamlit", "run", "app.py", "--server.port=8501", "--server.address=0.0.0.0", "--server.headless=true"]
