"""Main anomaly detection inference pipeline."""

import logging
import sys
from typing import Optional, List
from datetime import datetime
import pandas as pd

from devicedatahub_ml_engine.utils.db_connection import TimescaleDBConnection
from devicedatahub_ml_engine.anomaly_detector import (
    AnomalyDetector,
    AnomalyAggregator,
    AnomalyEvent,
)
from devicedatahub_ml_engine.anomaly_logger import AnomalyLogger, AnomalyAlert

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


class AnomalyDetectionPipeline:
    """End-to-end anomaly detection pipeline for WiFi telemetry."""

    def __init__(self, log_dir: str = "logs"):
        """
        Initialize the pipeline.

        Args:
            log_dir: Directory for anomaly logs
        """
        self.db = TimescaleDBConnection()
        self.detector = AnomalyDetector()
        self.aggregator = AnomalyAggregator(min_confidence=40.0)
        self.logger = AnomalyLogger(log_dir=log_dir)
        self.alerter = AnomalyAlert()

    def run_inference(
        self,
        device_id: Optional[str] = None,
        radio: Optional[str] = None,
        hours: int = 1,
    ) -> List[AnomalyEvent]:
        """
        Run full anomaly detection inference.

        Args:
            device_id: Specific device ID, or None for all
            radio: Specific radio, or None for all
            hours: How many hours back to scan

        Returns:
            List of detected anomalies
        """
        try:
            logger.info("=" * 70)
            logger.info(f"🔍 Starting anomaly detection inference")
            logger.info(f"   Device: {device_id or 'all'}, Radio: {radio or 'all'}, Hours: {hours}")
            logger.info("=" * 70)

            # Step 1: Connect to database
            if not self.db.connect():
                logger.error("Failed to connect to database. Aborting.")
                return []

            try:
                # Step 2: Fetch telemetry data with window aggregations
                anomalies = self._fetch_and_detect(device_id, radio, hours)

                # Step 3: Filter by confidence
                filtered_anomalies = self.aggregator.filter_by_confidence(anomalies)

                # Step 4: Log summary
                self.logger.log_summary(filtered_anomalies)

                # Step 5: Send alerts for high-severity anomalies
                if filtered_anomalies:
                    alert_count = self.alerter.send_batch_alerts(filtered_anomalies)
                    logger.info(f"Sent {alert_count} high-severity alerts")

                logger.info("=" * 70)
                logger.info(f"✅ Inference complete: {len(filtered_anomalies)} anomalies detected")
                logger.info("=" * 70)

                return filtered_anomalies

            finally:
                self.db.disconnect()

        except Exception as e:
            logger.error(f"Pipeline error: {e}", exc_info=True)
            return []

    def _fetch_and_detect(
        self,
        device_id: Optional[str],
        radio: Optional[str],
        hours: int,
    ) -> List[AnomalyEvent]:
        """
        Fetch telemetry with window functions and detect anomalies.

        Args:
            device_id: Optional specific device
            radio: Optional specific radio
            hours: Hours back to query

        Returns:
            List of detected anomaly events
        """
        anomalies = []

        # Get list of devices and radios to scan
        if device_id and radio:
            device_radio_pairs = [(device_id, radio)]
        else:
            device_radio_pairs = self._get_active_devices_radios(hours)

        logger.info(f"Scanning {len(device_radio_pairs)} device-radio pairs")

        for dev_id, rad in device_radio_pairs:
            logger.debug(f"Processing {dev_id}:{rad}")
            
            try:
                # Fetch aggregated metrics with window functions
                agg_row = self.db.fetch_anomaly_window_aggregate(
                    device_id=dev_id, radio=rad, window_minutes=5
                )

                if not agg_row:
                    logger.debug(f"No data for {dev_id}:{rad}")
                    continue

                # Detect anomalies in this row
                detected = self.detector.detect_anomalies(agg_row)
                if detected:
                    logger.info(
                        f"✓ Detected {len(detected)} anomaly(ies) for {dev_id}:{rad}"
                    )
                    anomalies.extend(detected)

            except Exception as e:
                logger.error(f"Error processing {dev_id}:{rad}: {e}", exc_info=True)
                continue

        return anomalies

    def _get_active_devices_radios(self, hours: int) -> List[tuple]:
        """
        Get list of (device_id, radio) pairs that have recent data.

        Args:
            hours: How many hours back to check

        Returns:
            List of (device_id, radio) tuples
        """
        query = f"""
        SELECT DISTINCT device_id, radio
        FROM public.telemetry
        WHERE timestamp > now() - interval '{hours} hours'
        ORDER BY device_id, radio
        """
        results = self.db.execute_query(query)
        return [(r["device_id"], r["radio"]) for r in results]

    def continuous_monitoring(
        self,
        interval_seconds: int = 300,
        max_iterations: Optional[int] = None,
    ) -> None:
        """
        Run anomaly detection in a continuous loop.

        Args:
            interval_seconds: Seconds between each run (default 5 min)
            max_iterations: Max number of iterations, or None for infinite
        """
        import time

        iteration = 0
        while max_iterations is None or iteration < max_iterations:
            try:
                logger.info(
                    f"[Iteration {iteration + 1}] "
                    f"Running anomaly detection at {datetime.now().isoformat()}"
                )
                self.run_inference(hours=1)

                iteration += 1
                if max_iterations and iteration >= max_iterations:
                    break

                logger.info(f"Sleeping for {interval_seconds}s until next run...")
                time.sleep(interval_seconds)

            except KeyboardInterrupt:
                logger.warning("Continuous monitoring stopped by user")
                break
            except Exception as e:
                logger.error(f"Error in continuous monitoring: {e}", exc_info=True)
                logger.info(f"Retrying in {interval_seconds}s...")
                time.sleep(interval_seconds)


def main():
    """Main entry point for anomaly detection."""
    import argparse

    parser = argparse.ArgumentParser(
        description="WiFi Telemetry Anomaly Detection Pipeline"
    )
    parser.add_argument(
        "--device-id",
        type=str,
        default=None,
        help="Specific device ID to scan (optional)",
    )
    parser.add_argument(
        "--radio",
        type=str,
        default=None,
        help="Specific radio to scan (optional)",
    )
    parser.add_argument(
        "--hours",
        type=int,
        default=1,
        help="Hours back to scan (default: 1)",
    )
    parser.add_argument(
        "--continuous",
        action="store_true",
        help="Run in continuous monitoring mode",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=300,
        help="Interval in seconds for continuous mode (default: 300)",
    )
    parser.add_argument(
        "--iterations",
        type=int,
        default=None,
        help="Max iterations in continuous mode (default: infinite)",
    )
    parser.add_argument(
        "--log-dir",
        type=str,
        default="logs",
        help="Directory for anomaly logs (default: logs)",
    )

    args = parser.parse_args()

    # Create and run pipeline
    pipeline = AnomalyDetectionPipeline(log_dir=args.log_dir)

    if args.continuous:
        logger.info("Starting continuous monitoring mode...")
        pipeline.continuous_monitoring(
            interval_seconds=args.interval,
            max_iterations=args.iterations,
        )
    else:
        pipeline.run_inference(
            device_id=args.device_id,
            radio=args.radio,
            hours=args.hours,
        )


if __name__ == "__main__":
    main()
