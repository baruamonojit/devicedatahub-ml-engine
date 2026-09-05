#!/bin/bash
# Run anomaly detection in continuous monitoring mode

set -e

# Load environment variables
if [ -f .env ]; then
    export $(cat .env | xargs)
fi

# Default values
INTERVAL=${1:-300}  # 5 minutes default
POLL_LIMIT=${2:-}   # No limit by default

echo "🚀 Starting continuous anomaly detection monitoring..."
echo "   Interval: ${INTERVAL}s (${INTERVAL}/60 = $((INTERVAL / 60)) min)"
if [ -n "$POLL_LIMIT" ]; then
    echo "   Max iterations: ${POLL_LIMIT}"
fi

# Run the anomaly detection pipeline in continuous mode
python -m devicedatahub_ml_engine.anomaly_inference \
    --continuous \
    --interval $INTERVAL \
    --log-dir logs \
    $([ -n "$POLL_LIMIT" ] && echo "--iterations $POLL_LIMIT")

echo "✅ Continuous monitoring completed"
