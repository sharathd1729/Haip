FROM python:3.12-slim

WORKDIR /app

# System deps — gcc for C extensions, libpq for psycopg2, ffmpeg for audio + marketing reels,
# fonts-noto-core for brand-kit typefaces on rendered posts (services/marketing_render.py)
RUN apt-get update && apt-get install -y \
    gcc \
    libpq-dev \
    ffmpeg \
    fonts-noto-core \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --upgrade pip setuptools wheel && \
    pip install --no-cache-dir -r requirements.txt

COPY . .

# Create uploads directory for local recording storage
RUN mkdir -p /app/uploads

EXPOSE 8000

# Health check — uses $PORT so it works on Railway and local
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=5 \
    CMD curl -f http://localhost:${PORT:-8000}/health || exit 1

# Run migrations then start gunicorn bound to Railway's dynamic $PORT
CMD ["sh", "-c", "alembic upgrade head && gunicorn app.main:app --worker-class uvicorn.workers.UvicornWorker --workers 2 --bind 0.0.0.0:${PORT:-8000} --timeout 120 --keep-alive 5 --access-logfile - --error-logfile -"]
