# 🚀 Implementation Guide: Anomaly Detection & Congestion Forecasting

## Executive Summary

A complete production-grade **anomaly detection system** has been implemented for your WiFi telemetry data. It detects 5 types of anomalies in real-time using TimescaleDB window functions and logs results for monitoring.

**Key Features:**
- ✅ Uses database window functions (no Python in-memory aggregation)
- ✅ Detects congestion forecasting (easy starter use case)
- ✅ Continuous monitoring support (poll every N seconds)
- ✅ Structured JSON logging to `logs/anomalies.jsonl`
- ✅ Severity-based alerts (low → critical)
- ✅ Extensible architecture for custom rules

## 📁 What Was Created

### Code Files

| File | Purpose |
|------|---------|
| `devicedatahub_ml_engine/utils/db_connection.py` | DB connectivity + window functions |
| `devicedatahub_ml_engine/anomaly_detector.py` | Detection rules engine (5 anomaly types) |
| `devicedatahub_ml_engine/anomaly_logger.py` | Structured logging + alerting |
| `devicedatahub_ml_engine/anomaly_inference.py` | Main pipeline orchestrator |
| `test_anomaly_setup.py` | Validation tests |

### Configuration
- `.env` - Database credentials & thresholds
- `ANOMALY_DETECTION.md` - Comprehensive documentation

### Scripts
- `scripts/run_anomaly_detection.sh` - Single run (scan last 1 hour)
- `scripts/run_continuous_anomaly_monitoring.sh` - Continuous polling

## 🎯 Detected Anomalies

### 1. **Congestion High** (Your Use Case)
**When:** `channel_utilization_pct > 70%` (or `> 85%` for critical)
**Why:** Forecasts QoE degradation, capacity planning alert
**Severity:** LOW → CRITICAL (depends on utilization level & OBSS presence)

```
Example:
  channel_utilization_pct: 87%
  OBSS: 45%  
  same_channel_ap_count: 8
  → Severity: CRITICAL (score=95)
```

### 2. **Retry Spike**
**When:** `tx_retries_delta > 300` OR `z-score > 2.5`
**Why:** Sudden link degradation (interference, weak signal)
**Severity:** LOW → CRITICAL

### 3. **RSSI Degradation**
**When:** `avg_rssi_dbm < -70 dBm`
**Why:** Weak signal predicts low throughput
**Severity:** LOW → HIGH

### 4. **Interference Spike**
**When:** `OBSS > 40%` + own utilization < 50%
**Why:** External WiFi congestion (not caused by us)
**Severity:** MEDIUM → HIGH

### 5. **Link Failure**
**When:** `tx_failed_delta > 10`
**Why:** QoS collapse, severe RF issues
**Severity:** CRITICAL

## 🏃 Quick Start (3 Steps)

### Step 1: Verify Setup
```bash
cd /root/workspaces/python/devicedatahub-ml-engine
python test_anomaly_setup.py
```

**Expected Output:**
```
✅ PASS: Imports
✅ PASS: Config
✅ PASS: Logger
✅ PASS: Detector
✅ PASS: Database
Result: 5/5 tests passed! Ready to run anomaly detection.
```

### Step 2: Run Single Inference
```bash
# Scan last 1 hour for all devices
python -m devicedatahub_ml_engine.anomaly_inference --hours 1

# Or use the wrapper script
bash scripts/run_anomaly_detection.sh
```

### Step 3: Review Logs
```bash
# View detected anomalies as JSON
cat logs/anomalies.jsonl | jq

# Filter by anomaly type
cat logs/anomalies.jsonl | jq '.message | select(.anomaly_type == "congestion_high")'

# Filter by severity
cat logs/anomalies.jsonl | jq '.message | select(.severity == "critical")'
```

## 📊 Output Example

### Console Output
```
======================================================================
🔍 Starting anomaly detection inference
   Device: all, Radio: all, Hours: 1
======================================================================
Scanning 2 device-radio pairs
✓ Detected 2 anomaly(ies) for device-001:5GHz
✓ Detected 1 anomaly(ies) for device-002:2.4GHz
📊 ANOMALY SUMMARY: 3 anomaly(ies) detected
   By Type: {'retry_spike': 1, 'congestion_high': 2}
   By Severity: {'high': 1, 'critical': 2}
   device-001:5GHz: 2 anomaly(ies) [CRITICAL]
   device-002:2.4GHz: 1 anomaly(ies) [HIGH]
✅ Inference complete: 3 anomalies detected
```

### Log File (logs/anomalies.jsonl)
```json
{
  "timestamp": "2024-09-05T14:32:15",
  "level": "INFO",
  "message": {
    "device_id": "device-001",
    "radio": "5GHz",
    "anomaly_type": "congestion_high",
    "severity": "critical",
    "score": 95.0,
    "message": "High congestion forecasted (util=87%, OBSS=45%, neighbors=8)",
    "affected_metrics": {
      "channel_utilization_pct": 87.5,
      "obss_utilization_pct": 45.0,
      "same_channel_ap_count": 8
    }
  }
}
```

## 🔄 Production Deployment Options

### Option A: Cron Job (Periodic Scanning)
```bash
# Every 5 minutes, scan last hour for anomalies
*/5 * * * * /root/workspaces/python/devicedatahub-ml-engine/scripts/run_anomaly_detection.sh >> /var/log/anomaly_detection.log 2>&1
```

### Option B: Systemd Service (Continuous Monitoring)
Create `/etc/systemd/system/anomaly-detector.service`:
```ini
[Unit]
Description=WiFi Telemetry Anomaly Detection
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/root/workspaces/python/devicedatahub-ml-engine
ExecStart=bash scripts/run_continuous_anomaly_monitoring.sh 300
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Start service:
```bash
sudo systemctl daemon-reload
sudo systemctl enable anomaly-detector
sudo systemctl start anomaly-detector
sudo systemctl status anomaly-detector
```

### Option C: Docker Container
```dockerfile
FROM python:3.9
WORKDIR /app
COPY . .
RUN pip install -r requirements.txt
CMD ["python", "-m", "devicedatahub_ml_engine.anomaly_inference", "--continuous", "--interval", "300"]
```

## ⚙️ Customization

### Adjust Detection Thresholds
Edit `.env` or modify in Python:
```python
from devicedatahub_ml_engine.anomaly_detector import AnomalyDetector

# Custom thresholds
thresholds = {
    "tx_retries_delta_high": 500,  # was 300
    "utilization_critical": 90,     # was 85
    "zscore_threshold": 3.0,        # was 2.5
}
detector = AnomalyDetector(thresholds=thresholds)
```

### Change Minimum Confidence Score
Filter low-confidence anomalies:
```bash
python -m devicedatahub_ml_engine.anomaly_inference --hours 1
# MIN_CONFIDENCE_SCORE=60 (in .env or code)
```

### Add Slack Alerts
Extend `AnomalyAlert` class in `anomaly_logger.py`:
```python
class SlackAnomalyAlert(AnomalyAlert):
    def send_alert(self, anomaly):
        super().send_alert(anomaly)
        webhook_url = os.getenv("SLACK_WEBHOOK")
        requests.post(webhook_url, json={"text": anomaly.message})
        return True
```

## 🔍 Troubleshooting

### Issue: Database Connection Failed
```bash
# Verify DB is running and credentials are correct
psql -h localhost -p 5433 -U postgres -d telemetry \
    -c "SELECT COUNT(*) FROM telemetry;"

# Check .env file
cat .env | grep DB_
```

### Issue: No Anomalies Detected
```bash
# Check if telemetry data exists
psql -h localhost -p 5433 -U postgres -d telemetry \
    -c "SELECT MAX(timestamp) FROM telemetry;"

# Lower confidence threshold
# MIN_CONFIDENCE_SCORE=20

# Or lower detection thresholds:
# utilization_high: 60 (was 70)
# tx_retries_delta_high: 200 (was 300)
```

### Issue: Too Many False Positives
```bash
# Increase confidence threshold
# MIN_CONFIDENCE_SCORE=70

# Or increase detection thresholds:
# zscore_threshold: 3.5 (was 2.5)
# utilization_critical: 95 (was 85)
```

## 📚 API Reference

### Run Single Inference
```bash
python -m devicedatahub_ml_engine.anomaly_inference \
    [--device-id DEVICE_ID] \
    [--radio RADIO] \
    [--hours HOURS] \
    [--log-dir LOG_DIR]
```

### Run Continuous Monitoring
```bash
python -m devicedatahub_ml_engine.anomaly_inference \
    --continuous \
    [--interval SECONDS] \
    [--iterations N] \
    [--log-dir LOG_DIR]
```

### Python API
```python
from devicedatahub_ml_engine.anomaly_inference import AnomalyDetectionPipeline

pipeline = AnomalyDetectionPipeline(log_dir="logs")

# Single run
anomalies = pipeline.run_inference(device_id="dev-001", radio="5GHz", hours=2)

# Continuous monitoring
pipeline.continuous_monitoring(interval_seconds=300, max_iterations=None)
```

## 📈 Success Metrics

After deployment, track:
- **Detection Rate:** Anomalies detected per hour
- **False Positive Rate:** % of low-severity anomalies that don't impact users
- **Alert Response Time:** Time from detection to alert ≤ 1 minute
- **Coverage:** % of devices/radios with recent data

## 🎓 Learning Resources

- [Window Functions Guide](ANOMALY_DETECTION.md#-components) - `db_connection.py`
- [Anomaly Types](ANOMALY_DETECTION.md#-anomaly-types-detected) - Full specifications
- [Configuration Options](ANOMALY_DETECTION.md#-configuration) - Customization
- [Advanced Usage](ANOMALY_DETECTION.md#-advanced-usage) - Custom detectors

## ✅ Validation Checklist

- [ ] Ran `test_anomaly_setup.py` with 5/5 passing
- [ ] Successfully ran `anomaly_inference.py --hours 1`
- [ ] Verified `logs/anomalies.jsonl` file created
- [ ] Checked for expected anomalies in output
- [ ] Configured `.env` with correct DB credentials
- [ ] Tested on representative data (1-2 hours of telemetry)
- [ ] Set up chosen deployment option (cron/systemd/docker)

## 🚀 Next Phase Recommendations

1. **Monitor for 1 week** - Tune thresholds based on real alerts
2. **Build feedback loop** - Label true vs. false anomalies
3. **Train ML model** - Use labels to build supervised classifier
4. **Dashboard integration** - Visualize in Grafana/DataDog
5. **Alerting integration** - Connect to PagerDuty/OpsGenie

---

**Questions?** Review [ANOMALY_DETECTION.md](./ANOMALY_DETECTION.md) for comprehensive documentation.
