# One image for every copy of the app. Build from the repository root:
#     docker build -f backend/Dockerfile -t lenden-saathi .
# Secrets are NEVER baked in: they come from the environment when the container starts (see deploy/loadbalancer/).
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    WEB_CONCURRENCY=2 \
    GUNICORN_THREADS=4

WORKDIR /app
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ /app/backend/
COPY database/ /app/database/
WORKDIR /app/backend

# Static files are collected once while building, so every copy serves them without any start-up work.
# The values below exist only for this build step; nothing sensitive is needed to collect static files.
RUN DJANGO_SECRET_KEY=build-only USE_LOCAL_DB=1 DJANGO_DEBUG=false python manage.py collectstatic --noinput \
    && useradd --system --no-create-home app \
    && chown -R app /app

USER app
EXPOSE 8000

# Reports healthy only when the app answers. "localhost" must stay in DJANGO_ALLOWED_HOSTS (the compose file keeps it there).
HEALTHCHECK --interval=15s --timeout=5s --start-period=40s --retries=3 \
    CMD python -c "import urllib.request as u; u.urlopen(u.Request('http://127.0.0.1:8000/health/live', headers={'Host': 'localhost'}), timeout=4)"

# One process family per container: WEB_CONCURRENCY workers x GUNICORN_THREADS threads. To serve more traffic start MORE containers
# (docker compose up --scale app=N) instead of making one container bigger. exec lets the container receive stop signals.
CMD ["sh", "-c", "exec gunicorn config.wsgi:application --bind 0.0.0.0:8000 --worker-class gthread --workers ${WEB_CONCURRENCY} --threads ${GUNICORN_THREADS} --worker-tmp-dir /dev/shm --timeout 60 --graceful-timeout 30 --access-logfile -"]
