#!/bin/bash
# Run anomaly detection inference once

set -e

# Load environment variables
if [ -f .env ]; then
    export $(cat .env | xargs)
fi

# Run the anomaly detection pipeline
echo "🔍 Running anomaly detection inference..."
python -m devicedatahub_ml_engine.anomaly_inference \
    --hours 1 \
    --log-dir logs

echo "✅ Anomaly detection complete"
