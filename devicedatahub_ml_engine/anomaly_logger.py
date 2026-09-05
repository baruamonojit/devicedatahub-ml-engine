"""Anomaly logging and alerting system."""

import logging
import json
from datetime import datetime
from typing import List, Dict, Any
from pathlib import Path

logger = logging.getLogger(__name__)


class AnomalyLogger:
    """Logs anomaly detections to file and/or structured logging."""

    def __init__(self, log_dir: str = "logs"):
        """
        Initialize anomaly logger.

        Args:
            log_dir: Directory to store anomaly logs
        """
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(exist_ok=True)

        # Setup anomaly-specific logger
        self.anomaly_logger = logging.getLogger("anomaly_detector")
        
        # File handler for anomalies
        anomaly_file = self.log_dir / "anomalies.jsonl"
        file_handler = logging.FileHandler(anomaly_file)
        file_handler.setLevel(logging.INFO)
        
        # JSON formatter for structured logging
        formatter = logging.Formatter(
            '{"timestamp": "%(asctime)s", "level": "%(levelname)s", "message": %(message)s}',
            datefmt="%Y-%m-%dT%H:%M:%S",
        )
        file_handler.setFormatter(formatter)
        self.anomaly_logger.addHandler(file_handler)
        self.anomaly_logger.setLevel(logging.INFO)

    def log_anomaly(self, anomaly: "AnomalyEvent") -> None:  # noqa: F821
        """
        Log a single anomaly event.

        Args:
            anomaly: AnomalyEvent to log
        """
        anomaly_dict = anomaly.to_dict()
        anomaly_dict["timestamp"] = str(anomaly_dict["timestamp"])
        self.anomaly_logger.info(json.dumps(anomaly_dict))
        
        # Also log to console at appropriate level
        level = {
            "critical": logging.CRITICAL,
            "high": logging.ERROR,
            "medium": logging.WARNING,
            "low": logging.INFO,
        }.get(anomaly.severity, logging.INFO)
        
        logger.log(
            level,
            f"🚨 ANOMALY [{anomaly.severity.upper()}] {anomaly.anomaly_type}: "
            f"{anomaly.message} (score={anomaly.score}, device={anomaly.device_id}, radio={anomaly.radio})",
        )

    def log_batch(self, anomalies: List["AnomalyEvent"]) -> None:  # noqa: F821
        """
        Log multiple anomalies.

        Args:
            anomalies: List of AnomalyEvent objects
        """
        for anomaly in anomalies:
            self.log_anomaly(anomaly)

    def log_summary(self, anomalies: List["AnomalyEvent"]) -> None:  # noqa: F821
        """
        Log a summary report of anomalies.

        Args:
            anomalies: List of AnomalyEvent objects
        """
        if not anomalies:
            logger.info("✅ No anomalies detected in this run")
            return

        # Count by type and severity
        by_type = {}
        by_severity = {}
        for anomaly in anomalies:
            by_type[anomaly.anomaly_type] = by_type.get(anomaly.anomaly_type, 0) + 1
            by_severity[anomaly.severity] = by_severity.get(anomaly.severity, 0) + 1

        logger.info(f"📊 ANOMALY SUMMARY: {len(anomalies)} anomaly(ies) detected")
        logger.info(f"   By Type: {by_type}")
        logger.info(f"   By Severity: {by_severity}")

        # Group and report by device/radio
        by_device_radio = {}
        for anomaly in anomalies:
            key = f"{anomaly.device_id}:{anomaly.radio}"
            if key not in by_device_radio:
                by_device_radio[key] = []
            by_device_radio[key].append(anomaly)

        for device_radio, device_anomalies in by_device_radio.items():
            severities = [a.severity for a in device_anomalies]
            max_severity = max(
                {"critical": 4, "high": 3, "medium": 2, "low": 1}.get(s, 0)
                for s in severities
            )
            severity_map = {4: "CRITICAL", 3: "HIGH", 2: "MEDIUM", 1: "LOW"}
            logger.warning(
                f"   {device_radio}: {len(device_anomalies)} anomaly(ies) "
                f"[{severity_map.get(max_severity, 'LOW')}]"
            )

    def get_recent_anomalies(self, days: int = 1) -> List[Dict[str, Any]]:
        """
        Read and parse recent anomalies from log file.

        Args:
            days: How many days back to read

        Returns:
            List of anomaly dictionaries
        """
        anomaly_file = self.log_dir / "anomalies.jsonl"
        if not anomaly_file.exists():
            return []

        cutoff_time = datetime.now().timestamp() - (days * 86400)
        anomalies = []

        with open(anomaly_file, "r") as f:
            for line in f:
                try:
                    record = json.loads(line)
                    # Extract timestamp from structured log
                    if "timestamp" in record:
                        ts_str = record["timestamp"]
                        ts = datetime.fromisoformat(ts_str).timestamp()
                        if ts >= cutoff_time:
                            # Parse the actual anomaly data from message
                            anomalies.append(record)
                except json.JSONDecodeError:
                    continue

        return anomalies


class AnomalyAlert:
    """Send alerts for high-severity anomalies (extensible for Slack, email, etc.)."""

    def __init__(self):
        """Initialize alerter."""
        pass

    def send_alert(self, anomaly: "AnomalyEvent") -> bool:  # noqa: F821
        """
        Send alert for high-severity anomaly.

        Args:
            anomaly: AnomalyEvent to alert on

        Returns:
            bool: True if alert sent successfully
        """
        if anomaly.severity not in ["high", "critical"]:
            return False

        # Log alert
        alert_msg = (
            f"🚨 ALERT [{anomaly.severity.upper()}]: {anomaly.anomaly_type} detected\n"
            f"Device: {anomaly.device_id}\n"
            f"Radio: {anomaly.radio}\n"
            f"Message: {anomaly.message}\n"
            f"Score: {anomaly.score}/100\n"
            f"Timestamp: {anomaly.timestamp}"
        )
        logger.error(alert_msg)

        # TODO: Extend with Slack, email, webhook, PagerDuty, etc.
        # For now, just log to console and file

        return True

    def send_batch_alerts(self, anomalies: List["AnomalyEvent"]) -> int:  # noqa: F821
        """
        Send alerts for batch of anomalies.

        Args:
            anomalies: List of AnomalyEvent objects

        Returns:
            Number of alerts sent
        """
        alert_count = 0
        for anomaly in anomalies:
            if self.send_alert(anomaly):
                alert_count += 1
        return alert_count
