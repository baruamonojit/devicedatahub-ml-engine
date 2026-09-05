# WiFi Congestion Detection Using Telemetry Metrics

## Overview

The anomaly detection system has been enhanced to use WiFi-specific congestion metrics directly from your telemetry source instead of generic statistical features. This provides more accurate and actionable congestion detection.

## Available Metrics

These 11 metrics from your telemetry source are now used for training and detection:

| Metric | Normal | Anomaly | Description |
|--------|--------|---------|-------------|
| `channel_utilization_pct` | ~4% | 80–95% | Channel heavily occupied |
| `cca_busy_pct` | ~4% | 80–95% | Clear-channel assessment busy |
| `tx_airtime_pct` | ~0% | 60–90% | AP spending lots of airtime transmitting |
| `rx_airtime_pct` | ~3% | 50–80% | Lots of received airtime |
| `noise_floor_dbm` | -92 | -75 to -80 | Increased RF noise |
| `neighbor_ap_count` | ~4 | 15–30 | Dense RF environment |
| `strong_neighbor_ap_count` | ~0 | 5–15 | Strong competing APs |
| `same_channel_ap_count` | ~4 | 10–20 | Co-channel contention |
| `strong_same_channel_ap_count` | ~0 | 5–10 | Strong co-channel interferers |
| `obss_utilization_pct` | ~0 | 30–70% | OBSS activity |
| `interference_utilization_pct` | ~0 | 20–60% | Non-WiFi/interference activity |

## Data Preparation

### Step 1: Ensure Telemetry Data Has All Metrics

Your training CSV should include all congestion metrics as columns:

```csv
timestamp,device_id,radio,channel_utilization_pct,cca_busy_pct,tx_airtime_pct,rx_airtime_pct,noise_floor_dbm,neighbor_ap_count,strong_neighbor_ap_count,same_channel_ap_count,strong_same_channel_ap_count,obss_utilization_pct,interference_utilization_pct
2026-09-05 10:00:00,device_A,5GHz,4,4,0,3,-92,4,0,4,0,0,0
2026-09-05 10:01:00,device_A,5GHz,85,87,65,55,-76,8,2,8,1,45,25
...
```

**Missing columns:** Metrics not present in input data are handled gracefully (skipped in features).

### Step 2: Train Model

```bash
python -m devicedatahub_ml_engine.train \
  --data data/training_data.csv \
  --out model_artifacts/model.pkl
```

**What happens:**
1. Extracts features for each metric: mean, max, min, std, trend (over the window)
2. Labels anomalies based on multi-indicator conditions:
   - High utilization + strong APs/elevated noise
   - High interference activity
3. Trains supervised LightGBM model (or unsupervised IsolationForest if single-class)
4. Saves model + feature columns + scaler for inference

**Example output:**
```
Dataset size: 250 samples
Features selected: 55
Label distribution:
0    200
1     50
...
✅ Model saved to model_artifacts/model.pkl
```

## Inference Methods

### Method 1: Real-time Anomaly Detection (using anomaly_inference.py)

Uses database window functions to fetch aggregated metrics and run detection rules:

```bash
python -m devicedatahub_ml_engine.anomaly_inference --hours 1
```

**Features detected:** Congestion, retry spikes, RSSI degradation, interference, link failures

**Example output:**
```
🔍 Starting anomaly detection inference
   Device: all, Radio: all, Hours: 1
...
Congestion detected (score=75): channel_util=87%, noise_floor=-76 dBm, obss=45%
✅ Inference complete: 5 anomalies detected
```

### Method 2: Batch ML Model Inference (using inference.py)

Loads trained model and runs inference loop:

```bash
export MODEL_PATH=model_artifacts/model.pkl
export ALERT_THRESHOLD=0.5
python -m devicedatahub_ml_engine.inference
```

**Features used:** All 11 congestion metrics (mean, max, min, std, trend per metric)

**Example output:**
```
🚨 ALERT: device=device_A anomaly_prob=0.87
✅ OK: device=device_B anomaly_score=0.32
```

## Congestion Scoring Logic

The system uses a multi-factor congestion score (0-100):

### Scoring Breakdown

- **Channel Utilization (0-40 pts):**
  - >85%: 40 pts (critical)
  - >70%: 25 pts (high)
  - >50%: 10 pts

- **CCA Busy (0-20 pts):**
  - >85%: 20 pts
  - >70%: 10 pts

- **Airtime Metrics (0-20 pts):**
  - TX airtime >60%: 10 pts
  - RX airtime >50%: 10 pts

- **Noise Floor (0-15 pts):**
  - >-75 dBm: 15 pts (elevated)
  - >-85 dBm: 8 pts

- **Interference (0-15 pts):**
  - >50%: 15 pts
  - >30%: 8 pts

- **OBSS (0-15 pts):**
  - >60%: 15 pts
  - >40%: 8 pts

- **AP Environment (0-10 pts):**
  - Strong co-channel APs >5: 10 pts
  - Co-channel APs >10: 5 pts

### Severity Mapping

- **Score < 30:** No anomaly
- **Score 30-45:** LOW severity
- **Score 45-65:** MEDIUM severity
- **Score 65-85:** HIGH severity
- **Score 85-100:** CRITICAL severity

## Integration with Your System

### Database Schema

Ensure your telemetry table has these columns:

```sql
CREATE TABLE telemetry (
  device_id TEXT,
  radio TEXT,
  timestamp TIMESTAMPTZ,
  channel_utilization_pct NUMERIC,
  cca_busy_pct NUMERIC,
  tx_airtime_pct NUMERIC,
  rx_airtime_pct NUMERIC,
  noise_floor_dbm NUMERIC,
  neighbor_ap_count INT,
  strong_neighbor_ap_count INT,
  same_channel_ap_count INT,
  strong_same_channel_ap_count INT,
  obss_utilization_pct NUMERIC,
  interference_utilization_pct NUMERIC,
  -- ... other fields
);
```

### Key Files Updated

1. **`utils/data.py`**
   - `build_features_from_df()`: Creates features from all 11 metrics
   - `build_features_for_inference()`: Normalizes single row for inference
   - `CONGESTION_METRICS`: List of all metrics

2. **`train.py`**
   - `make_labels()`: Uses multi-indicator conditions for anomaly labeling
   - `get_feature_columns()`: Dynamically selects available metrics
   - Model saved with: model, type, feature_columns, scaler

3. **`anomaly_detector.py`**
   - `_detect_congestion_forecast()`: Multi-factor congestion scoring (updated)
   - Considers all 11 metrics with weighted contributions

4. **`inference.py`**
   - Loads model + scaler + feature_columns metadata
   - Applies scaling before inference
   - Improved output formatting

## Troubleshooting

### "Missing columns" Error
- Ensure your CSV has all CONGESTION_METRICS columns
- Or suppress by setting missing values to 0 in data.py

### Low Model Accuracy
- Check training data quality (ensure anomaly labels are correct)
- Increase training data size (>500 samples recommended)
- Run `train.py` with `--data` pointing to larger dataset

### Inference Slow
- Decrease `POLL_INTERVAL_SECONDS` (default: 30)
- Use database read replicas for high-frequency queries

## Example Workflow

```bash
# 1. Prepare training data
python -c "import pandas as pd; df = pd.read_csv('raw_telemetry.csv'); df.to_csv('data/training_data.csv', index=False)"

# 2. Train model
python -m devicedatahub_ml_engine.train --data data/training_data.csv

# 3. Test with anomaly detection rules
python -m devicedatahub_ml_engine.anomaly_inference --hours 1

# 4. Run ML-based inference
python -m devicedatahub_ml_engine.inference

# 5. Review logs
cat logs/anomalies.jsonl | jq '.[] | {device_id, anomaly_type, severity, score}'
```

## Next Steps

1. **Collect representative telemetry data** with known congestion episodes
2. **Label training data** with correct anomaly ground truth
3. **Train and validate** using hold-out test set
4. **Deploy to production** with appropriate alert thresholds
5. **Monitor and retrain** as patterns evolve
