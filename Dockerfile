FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && playwright install --with-deps chromium

COPY main.py phase2_discover.py ./

# Seed list lands here; mount it to keep output on the host:
#   docker run -v ./data:/app/data mf-engine
RUN mkdir -p /app/data
VOLUME ["/app/data"]

CMD ["python", "main.py"]
