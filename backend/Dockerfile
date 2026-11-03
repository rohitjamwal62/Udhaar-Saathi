FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/ /app/backend/
COPY database/ /app/database/
WORKDIR /app/backend
EXPOSE 8000
# Run behind an HTTPS reverse proxy (Nginx/Caddy). Secrets come from the environment, never the image.
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "3"]
