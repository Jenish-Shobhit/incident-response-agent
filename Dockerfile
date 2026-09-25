FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    APP_ROOT=/app \
    MOCK=1 \
    PORT=8000

WORKDIR /app

RUN addgroup --system app && adduser --system --ingroup app app

# Dependencies first, so a code-only change reuses this layer.
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir .

COPY scenarios ./scenarios
COPY web ./web

USER app
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=3s --start-period=10s \
    CMD python -c "import urllib.request,os; urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\",\"8000\")}/health')"

CMD ["sh", "-c", "uvicorn incident_agent.api:app --host 0.0.0.0 --port ${PORT:-8000}"]
