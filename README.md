# DeviceDataHub ML Engine

WiFi congestion anomaly detection system using LightGBM with two-phase workflow:
1. **Pre-training:** Build model from historical radio_stats telemetry (JSON or CSV)
2. **Live inference:** Real-time 30-second polling with database window functions

The model directly ingests all database columns (30+ features) and uses ground-truth labels from training data to learn which combinations indicate anomalies (healthy vs problem).

## Prerequisites

- Python 3.10+ recommended
- A TimescaleDB (PostgreSQL) instance for live inference
- Training data in JSON or CSV format with labels

## Setup (virtual environment)

1. Create a virtual environment and activate it:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

2. Install dependencies:

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

## Phase 1: Pre-train Model from JSON Training Data

The recommended approach: train from JSON data with ground-truth labels provided by your radio_stats table.

### JSON Training Data Format

```json
{
  "description": "Flat radio_stats rows matching DB columns for ML training",
  "rows": [
    {
      "timestamp": "2026-09-05T10:00:00Z",
      "device_id": "WEH-587BE924EF9B",
      "radio": "2.4GHz",
      "ifname": "wlan0",
      "channel": 6,
      "channel_utilization_pct": 80.0,
      "cca_busy_pct": 93.0,
      "tx_airtime_pct": 41.0,
      "rx_airtime_pct": 39.0,
      "noise_floor_dbm": -87.0,
      "client_count": 23,
      "active_client_count": 11,
      "avg_rssi_dbm": -70.0,
      ...all radio_stats columns...,
      "label": 1,
      "scenario": "Severe congestion"
    },
    ...1000 total rows...
  ]
}
```

**Key points:**
- `label`: 0 = healthy, 1 = anomaly/problem
- All database columns from `radio_stats` table included
- Ground truth labels provided (not computed)

### Train Command

```bash
python3 -m devicedatahub_ml_engine.train \
  --data data/ml_radio_stats_train_1000.json \
  --out model_artifacts/model.pkl
```

### Training Process

1. **Loads JSON data** - Parses all 1000 samples with ground-truth labels
2. **Feature preparation** - Extracts 30 numeric features from database columns:
   - Channel metrics: `channel_utilization_pct`, `cca_busy_pct`, airtime rates
   - RF environment: `noise_floor_dbm`, AP counts, interference
   - Client metrics: `client_count`, `active_client_count`, weak client count
   - Performance: RSSI, SNR, throughput, MCS, NSS
   - Packet stats: retries, failures, TX/RX rates
3. **Feature scaling** - Normalizes all features with StandardScaler
4. **Model training** - LightGBM classifier on 800 training samples
5. **Evaluation** - Tests on 200 held-out samples

### Example Output

```
📥 Loading JSON training data from data/ml_radio_stats_train_1000.json...
   - Loaded 1000 samples
   - Available columns: 36

🔧 Preparing features...
   - Selected 30 numeric features

📊 Label distribution:
   - 0 (healthy): 414 samples (41.4%)
   - 1 (anomaly): 586 samples (58.6%)

🔀 Splitting data (80/20 train/test)...
🚀 Training LightGBM classifier...

              precision    recall  f1-score   support
   healthy       1.00      1.00      1.00        83
   anomaly       1.00      1.00      1.00       117
   accuracy                          1.00       200

🎯 ROC-AUC Score: 1.0000

⭐ Top 10 Important Features:
   channel_utilization_pct              196.0000
   tx_retries                           100.0000
   tx_airtime_pct                        81.0000
   ...

✅ Model saved to model_artifacts/model.pkl
   - Features: 30
   - Accuracy: 100.00%
```

## Phase 2: Live Inference (30-second polling)

Once trained, run continuous anomaly detection polling the database every 30 seconds.

### Setup Database Connection

```bash
export TS_HOST="your-timescaledb-host"
export TS_PORT="5432"
export TS_USER="postgres"
export TS_PASS="your-password"
export TS_DB="telemetry"
```

### Run Inference Loop

```bash
export MODEL_PATH="model_artifacts/model.pkl"
export ALERT_THRESHOLD="0.5"
export POLL_INTERVAL_SECONDS="30"

python3 -m devicedatahub_ml_engine.inference
```

### How It Works

Every 30 seconds:
1. **Fetches data** from TimescaleDB (window-aggregated metrics)
2. **Prepares features** - Extracts same 30 features as training
3. **Applies scaler** - Uses saved StandardScaler from training
4. **Runs prediction** - LightGBM model scores each device
5. **Alerts** - Prints 🚨 ALERT if anomaly probability >= threshold (0.5)

### Example Inference Output

```
[Poll #1] Fetching telemetry data...
   📊 Fetched 25 device measurements

   🎯 Running anomaly detection...
      ✅ healthy: device=WEH-587BE924EF9B anomaly_prob=0.12
      🚨 ALERT: device=WEH-ABC123XYZ anomaly_prob=0.89
      ✅ healthy: device=WEH-DEF456UVW anomaly_prob=0.34
   
   📈 Results: 23 healthy, 2 anomalies

   ⏱️  Next poll in 30s...
```

## Complete Workflow

```bash
# 1. Setup environment
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 2. Pre-train model from JSON data (one time)
python3 -m devicedatahub_ml_engine.train \
  --data data/ml_radio_stats_train_1000.json \
  --out model_artifacts/model.pkl

# 3. Configure database connection
export TS_HOST="your-host"
export TS_PORT="5432"
export TS_USER="postgres"
export TS_PASS="your-pass"
export TS_DB="telemetry"

# 4. Run live inference loop (continuous)
python3 -m devicedatahub_ml_engine.inference
```

## Model Details

The trained model wrapper contains:

```python
{
  "model": LGBMClassifier(...),
  "type": "supervised",
  "feature_columns": [
    "channel_utilization_pct",
    "tx_airtime_pct",
    "rx_airtime_pct",
    ...28 more features...
  ],
  "scaler": StandardScaler(),
  "model_version": "1.0",
  "training_info": {
    "total_samples": 1000,
    "training_samples": 800,
    "test_samples": 200,
    "feature_count": 30,
    "roc_auc": 1.0,
    "accuracy": 1.0
  }
}
```

Key components:
- **model**: Trained LightGBM classifier
- **feature_columns**: Exact feature order used during training (must match during inference)
- **scaler**: StandardScaler fitted on training data (applied to all inference data)
- **training_info**: Metadata about model quality and training stats

## Feature Importance (From Example Trained Model)

Top features for anomaly detection:
1. **channel_utilization_pct** (196.0) - Primary congestion indicator
2. **tx_retries** (100.0) - Link quality indicator
3. **tx_airtime_pct** (81.0) - AP transmission load
4. **rx_airtime_pct** (35.0) - Received traffic load
5. **avg_tx_rate_mbps** (28.0) - Throughput degradation signal
6. Client counts, noise levels, rates follow

This shows the model learns that **channel utilization, retries, and airtime** are most predictive of congestion anomalies.

## Testing

Test the training pipeline with provided JSON data:

```bash
python3 test_json_training.py
```

Expected output: Model trains successfully with ~100% accuracy on the test set.

## Troubleshooting

**"ModuleNotFoundError: No module named 'pandas'"**
- Ensure virtual environment is activated: `source .venv/bin/activate`
- Reinstall dependencies: `pip install -r requirements.txt`

**"No data returned from database"**
- Verify database credentials in environment variables
- Check that `radio_stats` table exists and has recent data
- Query the table directly to verify data availability

**Low model accuracy during training**
- Ensure JSON labels (0/1) are correct ground truth
- Consider collecting more diverse training samples
- Adjust train/test split or cross-validation

**Inference anomaly probabilities all low/high**
- Check that model was trained with similar data distribution
- Verify database is sending complete feature sets
- Retrain model with recent data if distribution changed
