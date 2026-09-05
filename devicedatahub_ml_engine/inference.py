import os
import time
import json
import pandas as pd
import numpy as np
from devicedatahub_ml_engine.models.io import load_model
from devicedatahub_ml_engine.utils.db import get_conn, fetch_window_features
from devicedatahub_ml_engine.utils.data import ML_FEATURE_COLUMNS

THRESHOLD = float(os.getenv('ALERT_THRESHOLD', '0.5'))
MODEL_PATH = os.getenv('MODEL_PATH', 'model_artifacts/model.pkl')
POLL_INTERVAL = int(os.getenv('POLL_INTERVAL_SECONDS', '30'))

def prepare_inference_data(row_data):
    """
    Prepare a single row for inference.
    
    Expects dict with all radio_stats columns.
    Extracts features used by the trained model.
    
    Args:
        row_data: Dict with telemetry data (all database columns)
        
    Returns:
        Dict with feature_name -> value for model input
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


def run_loop():
    """Run continuous anomaly detection loop using telemetry data from database."""
    print("="*70)
    print("Starting Inference Loop (30-second polling)")
    print("="*70)
    
    # Load model and metadata
    raw = load_model(MODEL_PATH)
    
    # Support wrapper dicts saved by train
    if isinstance(raw, dict) and 'model' in raw and 'type' in raw:
        model = raw['model']
        model_type = raw['type']
        feature_columns = raw.get('feature_columns', ML_FEATURE_COLUMNS)
        scaler = raw.get('scaler', None)
        model_version = raw.get('model_version', 'unknown')
    else:
        model = raw
        model_type = 'supervised' if hasattr(model, 'predict_proba') else 'unsupervised'
        feature_columns = ML_FEATURE_COLUMNS
        scaler = None
        model_version = 'unknown'

    print(f"\n📦 Model loaded:")
    print(f"   - Type: {model_type}")
    print(f"   - Version: {model_version}")
    print(f"   - Features: {len(feature_columns)}")
    print(f"   - Alert threshold: {THRESHOLD}")
    print(f"   - Poll interval: {POLL_INTERVAL}s")
    print("="*70)

    conn = get_conn()
    poll_count = 0
    
    try:
        while True:
            poll_count += 1
            print(f"\n[Poll #{poll_count}] Fetching telemetry data...")
            
            rows = fetch_window_features(conn)
            df = rows_to_df(rows)
            
            if df.empty:
                print("   ⚠️  No data returned from database")
            else:
                print(f"   📊 Fetched {len(df)} device measurements")
                
                # Extract features for each row
                X_list = []
                device_ids = []
                
                for _, row in df.iterrows():
                    row_dict = row.to_dict()
                    features_dict = prepare_inference_data(row_dict)
                    
                    # Convert to vector in feature column order
                    X_row = [features_dict.get(col, 0.0) for col in feature_columns]
                    X_list.append(X_row)
                    
                    device_ids.append(row_dict.get('device_id', 'unknown'))
                
                X = np.array(X_list)
                
                # Apply scaling if available
                if scaler is not None:
                    X_scaled = scaler.transform(X)
                else:
                    X_scaled = X
                
                # Run predictions
                print(f"\n   🎯 Running anomaly detection...")
                if model_type == 'supervised' and hasattr(model, 'predict_proba'):
                    probs = model.predict_proba(X_scaled)[:, 1]
                    
                    healthy_count = 0
                    anomaly_count = 0
                    
                    for device_id, prob in zip(device_ids, probs):
                        if prob >= THRESHOLD:
                            print(f"      🚨 ALERT: device={device_id} anomaly_prob={prob:.4f}")
                            anomaly_count += 1
                        else:
                            healthy_count += 1
                            # print(f"      ✅ OK: device={device_id} anomaly_prob={prob:.4f}")
                    
                    print(f"   📈 Results: {healthy_count} healthy, {anomaly_count} anomalies")
                else:
                    # Unsupervised scoring (IsolationForest)
                    if hasattr(model, 'decision_function'):
                        scores = -model.decision_function(X_scaled)
                    elif hasattr(model, 'score_samples'):
                        scores = -model.score_samples(X_scaled)
                    else:
                        preds = model.predict(X_scaled)
                        scores = (preds == -1).astype(float)

                    # Normalize scores to 0-1
                    minv = float(np.min(scores))
                    maxv = float(np.max(scores))
                    if maxv - minv > 0:
                        probs = (scores - minv) / (maxv - minv)
                    else:
                        probs = (scores > 0).astype(float)

                    healthy_count = 0
                    anomaly_count = 0
                    
                    for device_id, prob in zip(device_ids, probs):
                        if prob >= THRESHOLD:
                            print(f"      🚨 ALERT: device={device_id} anomaly_score={prob:.4f}")
                            anomaly_count += 1
                        else:
                            healthy_count += 1
                    
                    print(f"   📈 Results: {healthy_count} healthy, {anomaly_count} anomalies")
            
            print(f"   ⏱️  Next poll in {POLL_INTERVAL}s...")
            time.sleep(POLL_INTERVAL)
            
    except KeyboardInterrupt:
        print('\n\n⛔ Stopping inference loop')
    finally:
        conn.close()


if __name__ == '__main__':
    run_loop()
