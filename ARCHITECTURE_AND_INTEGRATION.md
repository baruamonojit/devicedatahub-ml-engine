# System Architecture & Integration Examples

## 🏗️ Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                     WiFi Telemetry Data Flow                        │
└─────────────────────────────────────────────────────────────────────┘

                         TimescaleDB
                      (telemetry table)
                            ↓
                ┌──────────────────────────┐
                │  TimescaleDB Window      │
                │  Functions               │
                │ ─────────────────────   │
                │ • AVG (5-min window)    │
                │ • LAG (deltas)          │
                │ • STDDEV (z-scores)     │
                │ • MIN/MAX (trends)      │
                └──────────────────────────┘
                            ↓
        ┌───────────────────────────────────────────┐
        │  AnomalyDetectionPipeline                 │
        │  (anomaly_inference.py)                   │
        │ ────────────────────────────────────────  │
        │ 1. Fetch aggregated metrics               │
        │ 2. Run detector on each device-radio      │
        │ 3. Filter by confidence                   │
        │ 4. Log results                            │
        └───────────────────────────────────────────┘
                            ↓
        ┌───────────────────────────────────────────┐
        │  Anomaly Types Detected                   │
        │────────────────────────────────────────── │
        │ ✓ Congestion High (easy use case)        │
        │ ✓ Retry Spike                            │
        │ ✓ RSSI Degradation                       │
        │ ✓ Interference Spike                     │
        │ ✓ Link Failure                           │
        └───────────────────────────────────────────┘
                            ↓
        ╔═══════════════════════════════════════════╗
        ║  Output: logs/anomalies.jsonl             ║
        ║  • JSON-Lines format (one per line)       ║
        ║  • Contains severity, score, metrics     ║
        ║  • Queryable for dashboards               ║
        ╚═══════════════════════════════════════════╝
```

## 📊 Data Flow Example: Congestion Detection

```
Telemetry Sample @ 14:32:00
┌──────────────────────────────┐
│ device_id: device-001        │
│ radio: 5GHz                  │
│ channel_utilization_pct: 87% │
│ obss_utilization_pct: 45%    │
│ same_channel_ap_count: 8     │
│ tx_retries_delta: 120        │
│ avg_rssi_dbm: -58            │
└──────────────────────────────┘
           ↓
    [Window Functions]
    (DB aggregates over 5-min window)
           ↓
┌──────────────────────────────────┐
│ util_avg_5m: 78%                 │
│ util_max_5m: 95%                 │
│ rssi_min_5m: -72 dBm             │
└──────────────────────────────────┘
           ↓
    [Anomaly Detector]
           ↓
    Checks: is channel_utilization > 85%?
    YES → severity = "critical", score = 95
           ↓
╔════════════════════════════════════════════════════════╗
║ AnomalyEvent                                           ║
║ ─────────────────────────────────────────────────────  ║
║ device_id: "device-001"                               ║
║ radio: "5GHz"                                          ║
║ timestamp: "2024-09-05 14:32:00"                       ║
║ anomaly_type: "congestion_high"                        ║
║ severity: "critical"                                   ║
║ score: 95.0                                            ║
║ msg: "High congestion forecasted (util=87%,            ║
║       OBSS=45%, neighbors=8)"                          ║
╚════════════════════════════════════════════════════════╝
           ↓
      [Logger.log_anomaly()]
           ↓
logs/anomalies.jsonl:
{
  "timestamp": "2024-09-05T14:32:00",
  "level": "INFO",
  "message": {
    "device_id": "device-001",
    "radio": "5GHz",
    "anomaly_type": "congestion_high",
    "severity": "critical",
    "score": 95.0,
    "message": "High congestion forecasted...",
    "affected_metrics": {
      "channel_utilization_pct": 87.5,
      "obss_utilization_pct": 45.0,
      "same_channel_ap_count": 8
    }
  }
}
```

## 🔄 Continuous Monitoring Flow

```
┌─────────────────────────────────────┐
│  Start Continuous Monitoring        │
│  (interval = 300s, max_iter = None) │
└─────────────────────────────────────┘
            ↓
    ┌───────────────────┐
    │ Iteration 1       │
    └───────────────────┘
    ├─ 14:00:00 Connect to DB
    ├─ 14:00:05 Fetch device-radio pairs
    ├─ 14:00:10 For each pair:
    │   ├─ Query window aggregates
    │   ├─ Detect anomalies
    │   ├─ Log results
    ├─ 14:00:30 Send high-severity alerts
    ├─ 14:00:35 Disconnect
    └─ 14:00:35 Sleep 300s
            ↓
    ┌───────────────────┐
    │ Iteration 2       │
    └───────────────────┘
    ├─ 14:05:00 Repeat
    ├─ 14:05:35 Sleep 300s
            ↓
    ┌───────────────────┐
    │ Iteration 3...    │
    │ continues forever │
    │ until Ctrl+C      │
    └───────────────────┘
```

## 🔌 Integration Patterns

### Pattern 1: Cron-Based Periodic Scanning
```bash
# Every 5 minutes, scan last hour
*/5 * * * * python -m devicedatahub_ml_engine.anomaly_inference --hours 1

# Logs accumulate in logs/anomalies.jsonl
```

**Pros:** Simple, minimal resource usage
**Cons:** Delayed detection (up to 5 min lag)

---

### Pattern 2: Continuous Daemon
```bash
# Run as background daemon (systemd)
python -m devicedatahub_ml_engine.anomaly_inference --continuous --interval 60
```

**Pros:** Real-time detection, immediate alerts
**Cons:** Continuous resource usage

---

### Pattern 3: Event-Driven (Future Enhancement)
```python
# Listen to MQTT/Kafka for new telemetry
# Trigger detection on each new sample
# (requires custom wrapper, not included)
```

**Pros:** True real-time, event-driven
**Cons:** More complex infrastructure

---

### Pattern 4: Dashboard Integration
```python
# Query logs + forward to Grafana/Datadog
results = anomaly_logger.get_recent_anomalies(days=1)
for anomaly in results:
    send_to_dashboard(anomaly)
```

## 📈 Scaling Considerations

### For 1,000 Devices × 2 Radios (2,000 device-radio pairs)

| Operation | Time | Notes |
|-----------|------|-------|
| DB query (device-radio list) | 100-500ms | Indexed on device_id, radio |
| Window aggregate per device-radio | 50-200ms | TimescaleDB hypertable optimized |
| Detector logic per sample | 5-20ms | Pure Python, minimal CPU |
| Total per run | ~45-60 seconds | For 2,000 pairs |
| Network I/O | ~2-5 seconds | Persistent connection, batch queries |

**Recommendation:** Run every 5-10 minutes for 1000+ devices.

## 🛠️ Example Code Integrations

### Integration 1: Custom Detector Subclass
```python
from devicedatahub_ml_engine.anomaly_detector import AnomalyDetector, AnomalyEvent

class CustomYourBusinessDetector(AnomalyDetector):
    """Add your business logic here."""
    
    def _detect_custom_sla_breach(self, row):
        """Detect SLA breach: util > 80% for > 10 min."""
        if row.get("util_avg_5m", 0) > 80:
            return AnomalyEvent(
                device_id=row.get("device_id"),
                radio=row.get("radio"),
                timestamp=str(row.get("timestamp")),
                anomaly_type="sla_breach",
                severity="high",
                score=80,
                message=f"SLA breach detected: avg util {row.get('util_avg_5m')}%",
                affected_metrics={"util_avg_5m": row.get("util_avg_5m")}
            )
        return None
    
    def detect_anomalies(self, row):
        anomalies = super().detect_anomalies(row)
        custom = self._detect_custom_sla_breach(row)
        if custom:
            anomalies.append(custom)
        return anomalies
```

### Integration 2: Send to Slack/PagerDuty
```python
from devicedatahub_ml_engine.anomaly_logger import AnomalyAlert
import requests

class AlertingSystem(AnomalyAlert):
    def send_alert(self, anomaly):
        super().send_alert(anomaly)
        
        if anomaly.severity == "critical":
            # Send to PagerDuty
            requests.post(
                "https://events.pagerduty.com/v2/enqueue",
                json={
                    "routing_key": os.getenv("PAGERDUTY_KEY"),
                    "event_action": "trigger",
                    "dedup_key": f"{anomaly.device_id}:{anomaly.anomaly_type}",
                    "payload": {
                        "summary": anomaly.message,
                        "severity": "critical",
                        "source": anomaly.device_id,
                        "custom_details": anomaly.affected_metrics,
                    }
                }
            )
        
        elif anomaly.severity == "high":
            # Send to Slack
            requests.post(
                os.getenv("SLACK_WEBHOOK"),
                json={
                    "text": f"⚠️ {anomaly.anomaly_type}: {anomaly.message}",
                    "attachments": [{
                        "color": "warning",
                        "fields": [
                            {"title": "Device", "value": anomaly.device_id},
                            {"title": "Radio", "value": anomaly.radio},
                            {"title": "Score", "value": anomaly.score},
                        ]
                    }]
                }
            )
        
        return True
```

### Integration 3: Feedback Loop for ML Training
```python
from devicedatahub_ml_engine.anomaly_inference import AnomalyDetectionPipeline

# Collect data for ML training
def collect_training_data():
    pipeline = AnomalyDetectionPipeline()
    
    # Get all anomalies from last 7 days
    anomalies = pipeline.logger.get_recent_anomalies(days=7)
    
    # Manually label as True/False Positive
    labeled = []
    for anomaly in anomalies:
        is_real = input(f"Is {anomaly['message']} real? (y/n): ")
        labeled.append({
            "anomaly": anomaly,
            "label": is_real == "y"
        })
    
    # Save for training
    import json
    with open("training_labels.jsonl", "w") as f:
        for item in labeled:
            f.write(json.dumps(item) + "\n")
    
    print(f"Collected {len(labeled)} labeled examples")

if __name__ == "__main__":
    collect_training_data()
```

## 📊 Metrics & KPIs

### Detection Effectiveness
```python
# After 1 week of monitoring, calculate:
true_positives = count(label=True)                    # Real issues user noticed
false_positives = count(label=False)                  # Non-issues
false_negatives = count(missed_but_user_reported)     # Missed real issues

precision = tp / (tp + fp)
recall = tp / (tp + fn)
f1_score = 2 * (precision * recall) / (precision + recall)
```

### Operational Metrics
```python
# Track in production:
anomalies_per_hour = count(anomalies) / hours_monitored
time_to_alert = avg(timestamp_detected - timestamp_occurred)
devices_covered = count(distinct device_id with recent data)
radio_coverage = count(distinct device_id:radio with anomalies) / total_device_radios
```

## 🔐 Security Considerations

- **Database credentials:** Use `.env` (never commit to git)
- **Log files:** Contain device_id, radio, metrics (PII/confidential)
- **Alerts:** If using Slack/PagerDuty, sanitize affected_metrics
- **Access control:** Restrict logs directory to authorized users

```bash
# Secure logs directory
chmod 700 logs/
chown app:app logs/
```

## 📝 Example: Production Deployment

### Step 1: Create systemd service
```bash
sudo tee /etc/systemd/system/anomaly-detector.service > /dev/null <<EOF
[Unit]
Description=WiFi Telemetry Anomaly Detection
After=network.target

[Service]
Type=simple
User=app
Group=app
WorkingDirectory=/opt/anomaly-detector
ExecStart=/usr/bin/python3 -m devicedatahub_ml_engine.anomaly_inference --continuous --interval 300
Restart=always
RestartSec=30
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable anomaly-detector
sudo systemctl start anomaly-detector
```

### Step 2: Monitor systemd service
```bash
# Check status
sudo systemctl status anomaly-detector

# View logs
sudo journalctl -u anomaly-detector -f

# Restart if needed
sudo systemctl restart anomaly-detector
```

### Step 3: Integrate with monitoring
```bash
# Forward logs to cloud logging (e.g., ELK, Splunk)
tail -f logs/anomalies.jsonl | \
    python -m json.tool | \
    curl -X POST -d @- http://splunk-endpoint/logs
```

---

**End of Architecture & Integration Guide**
