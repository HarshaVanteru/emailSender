FROM python:3.12-slim

# Prevent Python from writing .pyc files and enable unbuffered logging
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8000

WORKDIR /app

# Copy dependency definition and install packages
COPY requirements.txt .
# Normalize UTF-16LE encoding if requirements.txt was generated on Windows
RUN python -c "f = 'requirements.txt'; b = open(f, 'rb').read(); open(f, 'wb').write(b.decode('utf-16').encode('utf-8')) if b.startswith(b'\xff\xfe') else None" \
    && pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# Copy application source
COPY app ./app

# Create and switch to non-root user for security
RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

# Health check against the health endpoint--
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:4999/api/health')"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "4999"]