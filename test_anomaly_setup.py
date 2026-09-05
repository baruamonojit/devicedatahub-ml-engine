"""Test script to validate anomaly detection setup."""

import logging
import sys
import os
from pathlib import Path

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def test_imports():
    """Test that all required modules can be imported."""
    logger.info("Testing module imports...")
    try:
        from devicedatahub_ml_engine.utils.db_connection import TimescaleDBConnection
        from devicedatahub_ml_engine.anomaly_detector import (
            AnomalyDetector,
            AnomalyAggregator,
        )
        from devicedatahub_ml_engine.anomaly_logger import AnomalyLogger, AnomalyAlert
        from devicedatahub_ml_engine.anomaly_inference import AnomalyDetectionPipeline
        logger.info("✅ All imports successful")
        return True
    except ImportError as e:
        logger.error(f"❌ Import failed: {e}")
        return False


def test_database_connection():
    """Test connection to TimescaleDB."""
    logger.info("Testing database connection...")
    try:
        from devicedatahub_ml_engine.utils.db_connection import TimescaleDBConnection

        db = TimescaleDBConnection()
        if db.connect():
            logger.info("✅ Database connection successful")
            
            # Try to query table existence
            result = db.execute_query(
                "SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name='telemetry')"
            )
            if result and result[0].get("exists"):
                logger.info("✅ Telemetry table exists")
            else:
                logger.warning("⚠️  Telemetry table not found")
            
            db.disconnect()
            return True
        else:
            logger.error("❌ Database connection failed")
            return False
    except Exception as e:
        logger.error(f"❌ Database test failed: {e}")
        return False


def test_anomaly_detector():
    """Test anomaly detector with sample data."""
    logger.info("Testing anomaly detector...")
    try:
        from devicedatahub_ml_engine.anomaly_detector import AnomalyDetector

        detector = AnomalyDetector()

        # Test with normal data
        normal_row = {
            "device_id": "test-device",
            "radio": "5GHz",
            "timestamp": "2024-09-05 14:00:00",
            "tx_retries_delta": 50,
            "tx_retries_zscore": 0.5,
            "avg_rssi_dbm": -55,
            "channel_utilization_pct": 35,
            "obss_utilization_pct": 10,
            "tx_failed_delta": 0,
        }

        anomalies = detector.detect_anomalies(normal_row)
        if not anomalies:
            logger.info("✅ Normal data correctly identified (no anomalies)")
        else:
            logger.warning(f"⚠️  Normal data triggered anomalies: {anomalies}")

        # Test with anomalous data
        anomaly_row = {
            "device_id": "test-device",
            "radio": "5GHz",
            "timestamp": "2024-09-05 14:05:00",
            "tx_retries_delta": 500,  # High spike
            "tx_retries_zscore": 3.0,  # High z-score
            "avg_rssi_dbm": -75,  # Poor signal
            "channel_utilization_pct": 90,  # High congestion
            "cca_busy_pct": 88,
            "obss_utilization_pct": 50,  # High interference
            "same_channel_ap_count": 5,
            "tx_failed_delta": 15,  # Link failure
            "util_avg_5m": 80,
            "util_max_5m": 95,
            "rssi_min_5m": -80,
        }

        anomalies = detector.detect_anomalies(anomaly_row)
        if anomalies:
            logger.info(f"✅ Anomalous data detected {len(anomalies)} anomalies:")
            for anom in anomalies:
                logger.info(f"   - {anom.anomaly_type} (severity={anom.severity}, score={anom.score})")
            return True
        else:
            logger.error("❌ Anomalous data not detected")
            return False

    except Exception as e:
        logger.error(f"❌ Anomaly detector test failed: {e}")
        return False


def test_logger_setup():
    """Test anomaly logger setup."""
    logger.info("Testing anomaly logger setup...")
    try:
        from devicedatahub_ml_engine.anomaly_logger import AnomalyLogger

        log_dir = "test_logs"
        anom_logger = AnomalyLogger(log_dir=log_dir)

        # Check that log directory was created
        if Path(log_dir).exists():
            logger.info(f"✅ Log directory created: {log_dir}")
            # Clean up
            import shutil
            shutil.rmtree(log_dir)
            return True
        else:
            logger.error("❌ Log directory not created")
            return False

    except Exception as e:
        logger.error(f"❌ Logger test failed: {e}")
        return False


def test_config():
    """Test environment configuration."""
    logger.info("Testing environment configuration...")
    try:
        from dotenv import load_dotenv

        load_dotenv()

        required_env = [
            "DB_HOST",
            "DB_PORT",
            "DB_NAME",
            "DB_USER",
            "DB_PASSWORD",
            "DB_TABLE",
        ]

        missing = [var for var in required_env if not os.getenv(var)]

        if missing:
            logger.warning(f"⚠️  Missing environment variables: {missing}")
            logger.info("   Make sure .env file exists and is configured")
            return False
        else:
            logger.info("✅ All required environment variables configured")
            return True

    except ImportError:
        logger.warning("⚠️  python-dotenv not installed (optional)")
        return True
    except Exception as e:
        logger.error(f"❌ Config test failed: {e}")
        return False


def main():
    """Run all tests."""
    logger.info("=" * 70)
    logger.info("🧪 ANOMALY DETECTION SETUP VALIDATION")
    logger.info("=" * 70)

    tests = [
        ("Imports", test_imports),
        ("Config", test_config),
        ("Logger", test_logger_setup),
        ("Detector", test_anomaly_detector),
        ("Database", test_database_connection),
    ]

    results = {}
    for test_name, test_func in tests:
        try:
            results[test_name] = test_func()
        except Exception as e:
            logger.error(f"❌ Test '{test_name}' crashed: {e}")
            results[test_name] = False
        logger.info("-" * 70)

    # Summary
    logger.info("=" * 70)
    logger.info("📊 TEST SUMMARY")
    logger.info("=" * 70)
    passed = sum(1 for v in results.values() if v)
    total = len(results)

    for test_name, result in results.items():
        status = "✅ PASS" if result else "❌ FAIL"
        logger.info(f"{status}: {test_name}")

    logger.info("=" * 70)
    logger.info(f"Result: {passed}/{total} tests passed")
    logger.info("=" * 70)

    if passed == total:
        logger.info("✅ All tests passed! Ready to run anomaly detection.")
        return 0
    else:
        logger.error(f"❌ {total - passed} test(s) failed. Please check the logs.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
