"""Anomaly detection engine using window functions and statistical methods."""

import logging
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, asdict
from enum import Enum
import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


class AnomalyType(Enum):
    """Types of anomalies that can be detected."""

    RETRY_SPIKE = "retry_spike"
    RSSI_DEGRADATION = "rssi_degradation"
    CONGESTION_HIGH = "congestion_high"
    INTERFERENCE_SPIKE = "interference_spike"
    LINK_FAILURE = "link_failure"


@dataclass
class AnomalyEvent:
    """Represents a detected anomaly event."""

    device_id: str
    radio: str
    timestamp: str
    anomaly_type: str
    severity: str  # "low", "medium", "high", "critical"
    score: float  # 0-100
    message: str
    affected_metrics: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return asdict(self)


class AnomalyDetector:
    """Detects anomalies in WiFi telemetry using statistical methods."""

    # Thresholds for anomaly detection
    THRESHOLDS = {
        "tx_retries_delta_high": 300,  # packets per sample
        "tx_failed_high": 10,  # absolute count
        "rssi_degradation_threshold": -70,  # dBm - consider weak
        "utilization_critical": 85,  # percentage
        "utilization_high": 70,  # percentage
        "obss_interference_high": 40,  # percentage
        "zscore_threshold": 2.5,  # standard deviations
    }

    def __init__(self, thresholds: Optional[Dict[str, float]] = None):
        """
        Initialize anomaly detector.

        Args:
            thresholds: Optional custom thresholds to override defaults
        """
        if thresholds:
            self.THRESHOLDS.update(thresholds)

    def detect_anomalies(self, telemetry_row: Dict[str, Any]) -> List[AnomalyEvent]:
        """
        Detect anomalies in a single telemetry sample with computed window metrics.

        Args:
            telemetry_row: Dictionary with telemetry data and computed window functions

        Returns:
            List of detected anomaly events (can be empty).
        """
        anomalies = []

        # Extract values
        device_id = telemetry_row.get("device_id", "unknown")
        radio = telemetry_row.get("radio", "unknown")
        timestamp = str(telemetry_row.get("timestamp", ""))

        # 1. Detect retry spike anomaly
        retry_anomaly = self._detect_retry_spike(telemetry_row)
        if retry_anomaly:
            anomalies.append(retry_anomaly)

        # 2. Detect RSSI degradation (weak signal)
        rssi_anomaly = self._detect_rssi_degradation(telemetry_row)
        if rssi_anomaly:
            anomalies.append(rssi_anomaly)

        # 3. Detect high congestion (can forecast future issues)
        congestion_anomaly = self._detect_congestion_forecast(telemetry_row)
        if congestion_anomaly:
            anomalies.append(congestion_anomaly)

        # 4. Detect interference spike
        interference_anomaly = self._detect_interference_spike(telemetry_row)
        if interference_anomaly:
            anomalies.append(interference_anomaly)

        # 5. Detect link failure
        link_failure_anomaly = self._detect_link_failure(telemetry_row)
        if link_failure_anomaly:
            anomalies.append(link_failure_anomaly)

        return anomalies

    def _detect_retry_spike(self, row: Dict[str, Any]) -> Optional[AnomalyEvent]:
        """
        Detect sudden spike in transmission retries (indicates link degradation).

        High retries suggest RF interference, collisions, or weak link.
        """
        device_id = row.get("device_id", "unknown")
        radio = row.get("radio", "unknown")
        timestamp = str(row.get("timestamp", ""))

        tx_retries_delta = row.get("tx_retries_delta")
        tx_retries_zscore = row.get("tx_retries_zscore")
        avg_rssi_dbm = row.get("avg_rssi_dbm")

        # Skip if data not available
        if tx_retries_delta is None:
            return None

        # Detect using delta OR z-score
        is_delta_spike = (
            isinstance(tx_retries_delta, (int, float))
            and tx_retries_delta > self.THRESHOLDS["tx_retries_delta_high"]
        )
        is_zscore_anomaly = (
            isinstance(tx_retries_zscore, (int, float))
            and tx_retries_zscore > self.THRESHOLDS["zscore_threshold"]
        )

        if not (is_delta_spike or is_zscore_anomaly):
            return None

        # Calculate severity
        severity = "low"
        score = 40
        if is_delta_spike and tx_retries_delta > 500:
            severity = "high"
            score = 75
        if is_zscore_anomaly and tx_retries_zscore > 3.5:
            severity = "critical"
            score = 95

        # Additional context: if RSSI is also low, it's more severe
        if isinstance(avg_rssi_dbm, (int, float)) and avg_rssi_dbm < -70:
            severity = "high" if severity != "critical" else "critical"
            score = min(score + 15, 100)

        return AnomalyEvent(
            device_id=device_id,
            radio=radio,
            timestamp=timestamp,
            anomaly_type=AnomalyType.RETRY_SPIKE.value,
            severity=severity,
            score=score,
            message=f"TX retries spike detected (delta={tx_retries_delta}, zscore={tx_retries_zscore:.2f})",
            affected_metrics={
                "tx_retries_delta": tx_retries_delta,
                "tx_retries_zscore": tx_retries_zscore,
                "avg_rssi_dbm": avg_rssi_dbm,
            },
        )

    def _detect_rssi_degradation(self, row: Dict[str, Any]) -> Optional[AnomalyEvent]:
        """
        Detect weak signal (RSSI degradation) that impacts QoE.

        Poor RSSI (<-70 dBm) typically causes low throughput and high retries.
        """
        device_id = row.get("device_id", "unknown")
        radio = row.get("radio", "unknown")
        timestamp = str(row.get("timestamp", ""))

        avg_rssi_dbm = row.get("avg_rssi_dbm")
        min_rssi_dbm = row.get("min_rssi_dbm")
        rssi_min_5m = row.get("rssi_min_5m")

        # Skip if data not available
        if avg_rssi_dbm is None:
            return None

        # Check if average RSSI is weak
        is_weak_avg = avg_rssi_dbm < self.THRESHOLDS["rssi_degradation_threshold"]

        if not is_weak_avg:
            return None

        severity = "low"
        score = 35

        # More severe if minimum RSSI is critical
        if isinstance(min_rssi_dbm, (int, float)) and min_rssi_dbm < -80:
            severity = "high"
            score = 70

        # Or if trend is worsening
        if (isinstance(rssi_min_5m, (int, float)) and 
            isinstance(min_rssi_dbm, (int, float)) and 
            min_rssi_dbm < rssi_min_5m - 5):
            severity = "medium"
            score = 55

        return AnomalyEvent(
            device_id=device_id,
            radio=radio,
            timestamp=timestamp,
            anomaly_type=AnomalyType.RSSI_DEGRADATION.value,
            severity=severity,
            score=score,
            message=f"Weak signal detected (avg={avg_rssi_dbm} dBm, min={min_rssi_dbm} dBm)",
            affected_metrics={
                "avg_rssi_dbm": avg_rssi_dbm,
                "min_rssi_dbm": min_rssi_dbm,
                "rssi_min_5m": rssi_min_5m,
            },
        )

    def _detect_congestion_forecast(self, row: Dict[str, Any]) -> Optional[AnomalyEvent]:
        """
        Detect high congestion using WiFi-specific metrics from telemetry.

        Combines multiple indicators:
        - channel_utilization_pct: Own channel occupation (80-95% indicates congestion)
        - cca_busy_pct: Clear-channel assessment busy (80-95% indicates congestion)
        - tx_airtime_pct: AP transmission airtime (60-90% indicates heavy traffic)
        - rx_airtime_pct: Received airtime (50-80% indicates lots of activity)
        - noise_floor_dbm: RF noise level (-75 to -80 is elevated, -92 normal)
        - same_channel_ap_count: Co-channel contention (10-20 indicates dense environment)
        - strong_same_channel_ap_count: Strong interferers (5-10 indicates significant contention)
        - neighbor_ap_count: Total neighbors (15-30 in dense RF)
        - strong_neighbor_ap_count: Strong neighbors (5-15 indicates interference)
        - obss_utilization_pct: OBSS/external activity (30-70% indicates congestion)
        - interference_utilization_pct: Non-WiFi interference (20-60% indicates issues)
        """
        device_id = row.get("device_id", "unknown")
        radio = row.get("radio", "unknown")
        timestamp = str(row.get("timestamp", ""))

        # Core channel utilization metrics
        channel_util = row.get("channel_utilization_pct")
        cca_busy = row.get("cca_busy_pct")
        
        # Airtime metrics
        tx_airtime = row.get("tx_airtime_pct")
        rx_airtime = row.get("rx_airtime_pct")
        
        # Noise and interference
        noise_floor = row.get("noise_floor_dbm")
        interference_util = row.get("interference_utilization_pct")
        obss_util = row.get("obss_utilization_pct")
        
        # AP environment
        same_channel_ap = row.get("same_channel_ap_count")
        strong_same_channel_ap = row.get("strong_same_channel_ap_count")
        neighbor_ap_count = row.get("neighbor_ap_count")
        strong_neighbor_ap_count = row.get("strong_neighbor_ap_count")

        # Skip if no key metric available
        if channel_util is None and cca_busy is None and tx_airtime is None:
            return None

        # Score congestion based on multiple indicators
        congestion_score = 0
        indicators = []
        
        # Channel utilization indicator (0-40 points)
        if isinstance(channel_util, (int, float)):
            if channel_util > 85:
                congestion_score += 40
                indicators.append(f"channel_util={channel_util}% (critical)")
            elif channel_util > 70:
                congestion_score += 25
                indicators.append(f"channel_util={channel_util}% (high)")
            elif channel_util > 50:
                congestion_score += 10
        
        # CCA busy indicator (0-20 points)
        if isinstance(cca_busy, (int, float)):
            if cca_busy > 85:
                congestion_score += 20
                indicators.append(f"cca_busy={cca_busy}%")
            elif cca_busy > 70:
                congestion_score += 10
        
        # Airtime metrics (0-20 points)
        high_airtime = False
        if isinstance(tx_airtime, (int, float)) and tx_airtime > 60:
            congestion_score += 10
            high_airtime = True
            indicators.append(f"tx_airtime={tx_airtime}%")
        if isinstance(rx_airtime, (int, float)) and rx_airtime > 50:
            congestion_score += 10
            high_airtime = True
            indicators.append(f"rx_airtime={rx_airtime}%")
        
        # Noise elevation indicator (0-15 points)
        if isinstance(noise_floor, (int, float)):
            # Values are negative; -75 to -80 is elevated (normal is -92)
            if noise_floor > -75:
                congestion_score += 15
                indicators.append(f"noise_floor={noise_floor} dBm (elevated)")
            elif noise_floor > -85:
                congestion_score += 8
        
        # Interference indicator (0-15 points)
        if isinstance(interference_util, (int, float)):
            if interference_util > 50:
                congestion_score += 15
                indicators.append(f"interference={interference_util}%")
            elif interference_util > 30:
                congestion_score += 8
        
        # OBSS indicator (0-15 points)
        if isinstance(obss_util, (int, float)):
            if obss_util > 60:
                congestion_score += 15
                indicators.append(f"obss={obss_util}%")
            elif obss_util > 40:
                congestion_score += 8
        
        # AP environment density (0-10 points)
        if isinstance(strong_same_channel_ap, (int, float)) and strong_same_channel_ap > 5:
            congestion_score += 10
            indicators.append(f"strong_same_ch_ap={strong_same_channel_ap}")
        elif isinstance(same_channel_ap, (int, float)) and same_channel_ap > 10:
            congestion_score += 5
        
        # If congestion_score < 30, not significant
        if congestion_score < 30:
            return None

        # Determine severity
        severity = "low"
        if congestion_score < 45:
            severity = "low"
        elif congestion_score < 65:
            severity = "medium"
        elif congestion_score < 85:
            severity = "high"
        else:
            severity = "critical"

        return AnomalyEvent(
            device_id=device_id,
            radio=radio,
            timestamp=timestamp,
            anomaly_type=AnomalyType.CONGESTION_HIGH.value,
            severity=severity,
            score=min(congestion_score, 100),
            message=f"Congestion detected (score={congestion_score}): {', '.join(indicators)}",
            affected_metrics={
                "channel_utilization_pct": channel_util,
                "cca_busy_pct": cca_busy,
                "tx_airtime_pct": tx_airtime,
                "rx_airtime_pct": rx_airtime,
                "noise_floor_dbm": noise_floor,
                "interference_utilization_pct": interference_util,
                "obss_utilization_pct": obss_util,
                "same_channel_ap_count": same_channel_ap,
                "strong_same_channel_ap_count": strong_same_channel_ap,
                "neighbor_ap_count": neighbor_ap_count,
                "strong_neighbor_ap_count": strong_neighbor_ap_count,
                "congestion_score": congestion_score,
            },
        )

    def _detect_interference_spike(self, row: Dict[str, Any]) -> Optional[AnomalyEvent]:
        """
        Detect sudden spike in non-WiFi interference or OBSS.

        High OBSS/interference with moderate own utilization suggests external RF noise.
        """
        device_id = row.get("device_id", "unknown")
        radio = row.get("radio", "unknown")
        timestamp = str(row.get("timestamp", ""))

        obss_utilization = row.get("obss_utilization_pct")
        interference_utilization = row.get("interference_utilization_pct")
        channel_utilization = row.get("channel_utilization_pct")

        # Skip if data not available
        if obss_utilization is None:
            return None

        # Detect high external interference with our utilization not the culprit
        is_high_obss = obss_utilization > self.THRESHOLDS["obss_interference_high"]
        is_low_own = (
            isinstance(channel_utilization, (int, float)) and 
            channel_utilization < 50
        )

        if not (is_high_obss and is_low_own):
            return None

        severity = "medium"
        score = 60

        if obss_utilization > 60:
            severity = "high"
            score = 75

        return AnomalyEvent(
            device_id=device_id,
            radio=radio,
            timestamp=timestamp,
            anomaly_type=AnomalyType.INTERFERENCE_SPIKE.value,
            severity=severity,
            score=score,
            message=f"External interference/OBSS spike (OBSS={obss_utilization}%, interference={interference_utilization}%)",
            affected_metrics={
                "obss_utilization_pct": obss_utilization,
                "interference_utilization_pct": interference_utilization,
                "channel_utilization_pct": channel_utilization,
            },
        )

    def _detect_link_failure(self, row: Dict[str, Any]) -> Optional[AnomalyEvent]:
        """
        Detect severe link failure (high failed TX packets).

        TX failures indicate QoS collapse or hardware issues.
        """
        device_id = row.get("device_id", "unknown")
        radio = row.get("radio", "unknown")
        timestamp = str(row.get("timestamp", ""))

        tx_failed = row.get("tx_failed")
        tx_failed_delta = row.get("tx_failed_delta")

        # Skip if data not available
        if tx_failed is None:
            return None

        # Detect failure spike
        is_failure_spike = (
            isinstance(tx_failed_delta, (int, float)) and 
            tx_failed_delta > self.THRESHOLDS["tx_failed_high"]
        )

        if not is_failure_spike:
            return None

        return AnomalyEvent(
            device_id=device_id,
            radio=radio,
            timestamp=timestamp,
            anomaly_type=AnomalyType.LINK_FAILURE.value,
            severity="critical",
            score=90,
            message=f"Link failure detected (failed packets delta={tx_failed_delta})",
            affected_metrics={
                "tx_failed": tx_failed,
                "tx_failed_delta": tx_failed_delta,
            },
        )


class AnomalyAggregator:
    """Aggregate and filter anomalies by device/radio over time."""

    def __init__(self, min_confidence: float = 0.4):
        """
        Initialize aggregator.

        Args:
            min_confidence: Minimum anomaly score (0-100) to report (default: 40/100 = low)
        """
        self.min_confidence = min_confidence

    def filter_by_confidence(self, anomalies: List[AnomalyEvent]) -> List[AnomalyEvent]:
        """Filter anomalies by minimum confidence score."""
        return [a for a in anomalies if a.score >= self.min_confidence]

    def group_by_device_radio(
        self, anomalies: List[AnomalyEvent]
    ) -> Dict[str, List[AnomalyEvent]]:
        """Group anomalies by device_id + radio."""
        grouped = {}
        for anomaly in anomalies:
            key = f"{anomaly.device_id}:{anomaly.radio}"
            if key not in grouped:
                grouped[key] = []
            grouped[key].append(anomaly)
        return grouped

    def get_severity_level(self, anomalies: List[AnomalyEvent]) -> str:
        """Determine overall severity from a list of anomalies."""
        if not anomalies:
            return "none"
        severities = {"critical": 4, "high": 3, "medium": 2, "low": 1}
        max_severity = max(severities.get(a.severity, 0) for a in anomalies)
        severity_map = {4: "critical", 3: "high", 2: "medium", 1: "low"}
        return severity_map.get(max_severity, "low")
