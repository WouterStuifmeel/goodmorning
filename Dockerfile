FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml ./
COPY app ./app
COPY assets ./assets
COPY config ./config

RUN pip install --no-cache-dir .

ENV GOODMORNING_OUTPUT_DIR=/media/goodmorning
ENV GOODMORNING_DB_PATH=/data/jobs.sqlite3

VOLUME ["/media/goodmorning", "/data"]

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
