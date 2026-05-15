FROM python:3.12-slim

WORKDIR /app

# System deps — gcc for C extensions, libpq for psycopg2, ffmpeg for audio
RUN apt-get update && apt-get install -y \
    gcc \
    libpq-dev \
    ffmpeg \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Create uploads directory for local recording storage
RUN mkdir -p /app/uploads

EXPOSE 8000

# Health check — Railway/Render use this to know when the container is ready
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Production: gunicorn manages multiple uvicorn workers
# Development override: uvicorn app.main:app --reload --port 8000
CMD ["gunicorn", "app.main:app", \
     "--worker-class", "uvicorn.workers.UvicornWorker", \
     "--workers", "2", \
     "--bind", "0.0.0.0:8000", \
     "--timeout", "120", \
     "--keep-alive", "5", \
     "--access-logfile", "-", \
     "--error-logfile", "-"]
