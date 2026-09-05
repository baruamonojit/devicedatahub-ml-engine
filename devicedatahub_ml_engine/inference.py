import json
import os
import time
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

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
ANOMALY_LOG_DIR = Path(os.getenv("ANOMALY_LOG_DIR", "logs/anomalies"))


def json_safe(value):
    """Convert DB/numpy values into JSON-serializable Python types."""
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, (np.floating, np.integer)):
        return value.item()
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, float) and (np.isnan(value) or np.isinf(value)):
        return None
    if isinstance(value, dict):
        return {str(k): json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(v) for v in value]
    if pd.isna(value):
        return None
    return value


def to_jsonable_dict(row_dict):
    """Normalize a telemetry row dict for JSON logging / MQTT."""
    return {str(k): json_safe(v) for k, v in row_dict.items()}


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
                features_dict,
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

    for (device_id, radio, ts, row_dict, features_dict), prob in zip(meta, probs):
        results.append((device_id, radio, ts, float(prob), row_dict, features_dict))
    return results


def _log_anomaly_case(record: dict) -> Path:
    """
    Persist full anomaly input for offline replay/testing.

    Writes:
      - one JSONL line to logs/anomalies/anomalies.jsonl
      - one detailed JSON file per anomaly under logs/anomalies/
    """
    ANOMALY_LOG_DIR.mkdir(parents=True, exist_ok=True)
    safe_device = str(record.get("device_id", "unknown")).replace("/", "_")
    safe_radio = str(record.get("radio", "na")).replace("/", "_")
    ts_tag = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
    case_path = ANOMALY_LOG_DIR / f"anomaly_{safe_device}_{safe_radio}_{ts_tag}.json"

    with case_path.open("w", encoding="utf-8") as f:
        json.dump(record, f, indent=2, default=json_safe)

    with (ANOMALY_LOG_DIR / "anomalies.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, default=json_safe) + "\n")

    return case_path


def run_loop():
    """Run continuous anomaly detection loop using telemetry data from database."""
    print("=" * 70, flush=True)
    print("Starting Inference Loop (30-second polling)", flush=True)
    print("=" * 70, flush=True)

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

    print(f"\n📦 Model loaded:", flush=True)
    print(f"   - Type: {model_type}", flush=True)
    print(f"   - Version: {model_version}", flush=True)
    print(f"   - Features: {len(feature_columns)}", flush=True)
    print(f"   - Alert threshold: {THRESHOLD}", flush=True)
    print(f"   - Poll interval: {POLL_INTERVAL}s", flush=True)
    print(f"   - MQTT publishing: {MQTT_ENABLED}", flush=True)
    print(f"   - Anomaly log dir: {ANOMALY_LOG_DIR}", flush=True)
    print("=" * 70, flush=True)

    mqtt_pub = None
    if MQTT_ENABLED:
        mqtt_pub = MQTTAlertPublisher()
        if mqtt_pub.connect():
            print(
                f"   ✅ MQTT connected: "
                f"{mqtt_pub.broker_host}:{mqtt_pub.broker_port}",
                flush=True,
            )
        else:
            print(
                "   ⚠️  MQTT connect failed at startup; "
                "will retry on each anomaly publish",
                flush=True,
            )

    conn = get_conn()
    poll_count = 0

    try:
        while True:
            poll_count += 1
            print(f"\n[Poll #{poll_count}] Fetching telemetry data...", flush=True)

            try:
                rows = fetch_window_features(conn)
            except Exception as e:
                print(f"   ❌ DB fetch failed: {e}", flush=True)
                conn = get_conn()
                print(f"   ⏱️  Next poll in {POLL_INTERVAL}s...", flush=True)
                time.sleep(POLL_INTERVAL)
                continue

            df = rows_to_df(rows)

            if df.empty:
                print("   ⚠️  No data returned from database", flush=True)
            else:
                print(f"   📊 Fetched {len(df)} device measurements", flush=True)
                print(f"\n   🎯 Running anomaly detection...", flush=True)

                scored = _score_rows(model, model_type, scaler, feature_columns, df)
                healthy_count = 0
                anomaly_count = 0
                published = 0
                now_iso = datetime.now(timezone.utc).isoformat()

                for device_id, radio, ts, prob, row_dict, features_dict in scored:
                    if prob >= THRESHOLD:
                        anomaly_count += 1
                        print(
                            f"      🚨 ALERT: device={device_id} radio={radio} "
                            f"anomaly_prob={prob:.4f}",
                            flush=True,
                        )

                        input_row = to_jsonable_dict(row_dict)
                        features = {k: float(features_dict.get(k, 0.0)) for k in feature_columns}
                        anomaly_record = {
                            "detected_at": now_iso,
                            "poll": poll_count,
                            "device_id": str(device_id),
                            "radio": str(radio) if radio is not None else "",
                            "timestamp": json_safe(ts) if ts is not None else now_iso,
                            "anomaly_prob": float(prob),
                            "threshold": THRESHOLD,
                            "model_version": model_version,
                            "feature_columns": list(feature_columns),
                            "features": features,
                            "input_row": input_row,
                        }

                        case_path = _log_anomaly_case(anomaly_record)
                        print(
                            f"      📝 Anomaly input logged: {case_path}",
                            flush=True,
                        )
                        print(
                            "      🧾 Input details:\n"
                            + json.dumps(anomaly_record, indent=2, default=json_safe),
                            flush=True,
                        )

                        if mqtt_pub is not None:
                            payload = {
                                "device_id": anomaly_record["device_id"],
                                "radio": anomaly_record["radio"],
                                "timestamp": anomaly_record["timestamp"],
                                "anomaly_prob": anomaly_record["anomaly_prob"],
                                "threshold": THRESHOLD,
                                "model_version": model_version,
                                "features": features,
                                "input_row": input_row,
                                "metrics": {
                                    k: input_row.get(k)
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
                                    if k in input_row
                                },
                            }
                            if mqtt_pub.publish_anomaly_alert(device_id, payload):
                                published += 1
                            mqtt_pub.publish_device_status(
                                device_id,
                                "anomaly",
                                {
                                    "timestamp": anomaly_record["timestamp"],
                                    "anomaly_prob": float(prob),
                                },
                            )
                    else:
                        healthy_count += 1

                print(
                    f"   📈 Results: {healthy_count} healthy, "
                    f"{anomaly_count} anomalies",
                    flush=True,
                )
                if mqtt_pub is not None:
                    print(
                        f"   📡 Published {published} anomaly alert(s) to MQTT",
                        flush=True,
                    )
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

            print(f"   ⏱️  Next poll in {POLL_INTERVAL}s...", flush=True)
            time.sleep(POLL_INTERVAL)

    except KeyboardInterrupt:
        print("\n\n⛔ Stopping inference loop", flush=True)
    finally:
        conn.close()
        if mqtt_pub is not None:
            mqtt_pub.disconnect()


if __name__ == "__main__":
    run_loop()
