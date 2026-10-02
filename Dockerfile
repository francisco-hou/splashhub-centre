FROM python:3.11-slim
WORKDIR /app
# Debian security updates for the base image (the release gate blocks OS packages behind the fixed versions
# the scanner names). Same base and driver as the Mockup Hub, which already passes the platform's gates.
RUN apt-get update && apt-get upgrade -y --no-install-recommends && rm -rf /var/lib/apt/lists/*
# psycopg: the PostgreSQL driver for the run log (SPLUKI_POSTGRES). boto3: the S3 client for
# the copies of SOS package images in the app's bucket (SPLUKI_STORAGE) -- the same pin the
# Extension Hub ships with.
RUN pip install --no-cache-dir "psycopg[binary]==3.3.5" "boto3==1.40.50"
COPY app/ /app/
# The platform's Dockerfile policy blocks containers that run as root (Trivy DS-0002, HIGH).
RUN useradd --create-home --uid 10001 appuser
# Nothing here needs pip at runtime; removing it keeps the image-CVE gate clean.
RUN pip uninstall -y pip setuptools wheel 2>/dev/null || true
USER appuser
# SAMPLE_DATA=0: the image never seeds sample runs, whatever the backend.
# PYTHONUNBUFFERED: stdout/stderr reach the platform log at once instead of sitting in a buffer.
ENV HOST=0.0.0.0 PORT=8795 SAMPLE_DATA=0 PYTHONUNBUFFERED=1
EXPOSE 8795
CMD ["python", "server.py"]
