FROM python:3.12-slim

WORKDIR /app

# System deps for psycopg2 / lightgbm
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

COPY devicedatahub_ml_engine/ ./devicedatahub_ml_engine/

ENV PYTHONUNBUFFERED=1 \
    MODEL_PATH=model_artifacts/model.pkl \
    POLL_INTERVAL_SECONDS=30 \
    ALERT_THRESHOLD=0.5 \
    MQTT_ENABLED=true \
    MQTT_BASE_TOPIC=wifi/alerts

# Model artifacts mounted at runtime
VOLUME ["/app/model_artifacts"]

CMD ["python", "-m", "devicedatahub_ml_engine.inference"]
