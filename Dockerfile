FROM python:3.11-slim

# Keep Python output unbuffered so container logs stream in real time
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# Install deps first for better layer caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY app/ ./app/
COPY dashboard/ ./dashboard/
COPY scripts/ ./scripts/

# Data volume (SQLite lives here, shared between api + dashboard)
RUN mkdir -p /data

EXPOSE 8000 8501

# Default command is overridden per-service in docker-compose.yml
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
