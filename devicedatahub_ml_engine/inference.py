import os
import time
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from devicedatahub_ml_engine.models.io import load_model
from devicedatahub_ml_engine.mqtt_publisher import MQTTAlertPublisher
from devicedatahub_ml_engine.utils.db import get_conn, fetch_window_features
from devicedatahub_ml_engine.utils.data import ML_FEATURE_COLUMNS

THRESHOLD = float(os.getenv("ALERT_THRESHOLD", "0.5"))
MODEL_PATH = os.getenv("MODEL_PATH", "model_artifacts/model.pkl")
POLL_INTERVAL = int(os.getenv("POLL_INTERVAL_SECONDS", "30"))
MQTT_ENABLED = os.getenv("MQTT_ENABLED", "true").lower() in ("1", "true", "yes")


def prepare_inference_data(row_data):
    """
    Prepare a single row for inference.

    Expects dict with all radio_stats / telemetry columns.
    Extracts features used by the trained model.
    """
    features = {}
    for col in ML_FEATURE_COLUMNS:
        val = row_data.get(col, None)
        if val is not None:
            try:
                features[col] = float(val)
            except (ValueError, TypeError):
                features[col] = 0.0
        else:
            features[col] = 0.0
    return features


def rows_to_df(rows):
    """Convert database rows to DataFrame with ML features."""
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows)


def _score_rows(model, model_type, scaler, feature_columns, df):
    """Run model scoring; return list of (device_id, radio, timestamp, prob, row_dict)."""
    results = []
    X_list = []
    meta = []

    for _, row in df.iterrows():
        row_dict = row.to_dict()
        features_dict = prepare_inference_data(row_dict)
        X_row = [features_dict.get(col, 0.0) for col in feature_columns]
        X_list.append(X_row)
        meta.append(
            (
                row_dict.get("device_id", "unknown"),
                row_dict.get("radio", ""),
                row_dict.get("timestamp"),
                row_dict,
            )
        )

    X = pd.DataFrame(X_list, columns=feature_columns)
    X_scaled = scaler.transform(X) if scaler is not None else X.values

    if model_type == "supervised" and hasattr(model, "predict_proba"):
        probs = model.predict_proba(X_scaled)[:, 1]
    else:
        if hasattr(model, "decision_function"):
            scores = -model.decision_function(X_scaled)
        elif hasattr(model, "score_samples"):
            scores = -model.score_samples(X_scaled)
        else:
            preds = model.predict(X_scaled)
            scores = (preds == -1).astype(float)

        minv = float(np.min(scores))
        maxv = float(np.max(scores))
        if maxv - minv > 0:
            probs = (scores - minv) / (maxv - minv)
        else:
            probs = (scores > 0).astype(float)

    for (device_id, radio, ts, row_dict), prob in zip(meta, probs):
        results.append((device_id, radio, ts, float(prob), row_dict))
    return results


def run_loop():
    """Run continuous anomaly detection loop using telemetry data from database."""
    print("=" * 70)
    print("Starting Inference Loop (30-second polling)")
    print("=" * 70)

    raw = load_model(MODEL_PATH)

    if isinstance(raw, dict) and "model" in raw and "type" in raw:
        model = raw["model"]
        model_type = raw["type"]
        feature_columns = raw.get("feature_columns", ML_FEATURE_COLUMNS)
        scaler = raw.get("scaler", None)
        model_version = raw.get("model_version", "unknown")
    else:
        model = raw
        model_type = "supervised" if hasattr(model, "predict_proba") else "unsupervised"
        feature_columns = ML_FEATURE_COLUMNS
        scaler = None
        model_version = "unknown"

    print(f"\n📦 Model loaded:")
    print(f"   - Type: {model_type}")
    print(f"   - Version: {model_version}")
    print(f"   - Features: {len(feature_columns)}")
    print(f"   - Alert threshold: {THRESHOLD}")
    print(f"   - Poll interval: {POLL_INTERVAL}s")
    print(f"   - MQTT publishing: {MQTT_ENABLED}")
    print("=" * 70)

    mqtt_pub = None
    if MQTT_ENABLED:
        mqtt_pub = MQTTAlertPublisher()
        if mqtt_pub.connect():
            print(
                f"   ✅ MQTT connected: "
                f"{mqtt_pub.broker_host}:{mqtt_pub.broker_port}"
            )
        else:
            print(
                "   ⚠️  MQTT connect failed at startup; "
                "will retry on each anomaly publish"
            )

    conn = get_conn()
    poll_count = 0

    try:
        while True:
            poll_count += 1
            print(f"\n[Poll #{poll_count}] Fetching telemetry data...")

            try:
                rows = fetch_window_features(conn)
            except Exception as e:
                print(f"   ❌ DB fetch failed: {e}")
                conn = get_conn()
                print(f"   ⏱️  Next poll in {POLL_INTERVAL}s...")
                time.sleep(POLL_INTERVAL)
                continue

            df = rows_to_df(rows)

            if df.empty:
                print("   ⚠️  No data returned from database")
            else:
                print(f"   📊 Fetched {len(df)} device measurements")
                print(f"\n   🎯 Running anomaly detection...")

                scored = _score_rows(model, model_type, scaler, feature_columns, df)
                healthy_count = 0
                anomaly_count = 0
                published = 0
                now_iso = datetime.now(timezone.utc).isoformat()

                for device_id, radio, ts, prob, row_dict in scored:
                    if prob >= THRESHOLD:
                        anomaly_count += 1
                        print(
                            f"      🚨 ALERT: device={device_id} radio={radio} "
                            f"anomaly_prob={prob:.4f}"
                        )
                        if mqtt_pub is not None:
                            payload = {
                                "device_id": device_id,
                                "radio": radio,
                                "timestamp": str(ts) if ts is not None else now_iso,
                                "anomaly_prob": prob,
                                "threshold": THRESHOLD,
                                "model_version": model_version,
                                "metrics": {
                                    k: row_dict.get(k)
                                    for k in (
                                        "channel_utilization_pct",
                                        "cca_busy_pct",
                                        "tx_retries",
                                        "tx_failed",
                                        "avg_rssi_dbm",
                                        "obss_utilization_pct",
                                        "client_count",
                                        "active_client_count",
                                    )
                                    if k in row_dict
                                },
                            }
                            if mqtt_pub.publish_anomaly_alert(device_id, payload):
                                published += 1
                            mqtt_pub.publish_device_status(
                                device_id,
                                "anomaly",
                                {"timestamp": payload["timestamp"], "anomaly_prob": prob},
                            )
                    else:
                        healthy_count += 1

                print(
                    f"   📈 Results: {healthy_count} healthy, "
                    f"{anomaly_count} anomalies"
                )
                if mqtt_pub is not None:
                    print(f"   📡 Published {published} anomaly alert(s) to MQTT")
                    if mqtt_pub.connected or (
                        mqtt_pub.client is not None and mqtt_pub.client.is_connected()
                    ):
                        mqtt_pub.publish_batch_summary(
                            {
                                "poll": poll_count,
                                "timestamp": now_iso,
                                "total_rows": len(df),
                                "healthy_count": healthy_count,
                                "anomaly_count": anomaly_count,
                                "published": published,
                            }
                        )

            print(f"   ⏱️  Next poll in {POLL_INTERVAL}s...")
            time.sleep(POLL_INTERVAL)

    except KeyboardInterrupt:
        print("\n\n⛔ Stopping inference loop")
    finally:
        conn.close()
        if mqtt_pub is not None:
            mqtt_pub.disconnect()


if __name__ == "__main__":
    run_loop()
