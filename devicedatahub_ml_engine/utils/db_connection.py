"""Database connection and query utilities for TimescaleDB telemetry."""

import os
import logging
from typing import List, Dict, Any, Optional
import psycopg2
from psycopg2.extras import RealDictCursor
import pandas as pd

logger = logging.getLogger(__name__)


class TimescaleDBConnection:
    """Manages connection to TimescaleDB for telemetry data."""

    def __init__(self):
        """Initialize database connection parameters."""
        self.host = os.getenv("DB_HOST", "localhost")
        self.port = int(os.getenv("DB_PORT", 5433))
        self.database = os.getenv("DB_NAME", "telemetry")
        self.user = os.getenv("DB_USER", "postgres")
        self.password = os.getenv("DB_PASSWORD", "postgres")
        self.table = os.getenv("DB_TABLE", "telemetry")
        self.conn = None

    def connect(self) -> bool:
        """
        Establish connection to TimescaleDB.

        Returns:
            bool: True if connection successful, False otherwise.
        """
        try:
            self.conn = psycopg2.connect(
                host=self.host,
                port=self.port,
                database=self.database,
                user=self.user,
                password=self.password,
            )
            logger.info(f"Connected to TimescaleDB at {self.host}:{self.port}/{self.database}")
            return True
        except psycopg2.Error as e:
            logger.error(f"Failed to connect to TimescaleDB: {e}")
            return False

    def disconnect(self):
        """Close database connection."""
        if self.conn:
            self.conn.close()
            logger.info("Disconnected from TimescaleDB")

    def execute_query(self, query: str, params: tuple = None) -> List[Dict[str, Any]]:
        """
        Execute a SELECT query and return results as list of dicts.

        Args:
            query: SQL query string
            params: Query parameters (optional)

        Returns:
            List of dictionaries representing query results.
        """
        try:
            with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(query, params)
                results = cur.fetchall()
                return [dict(row) for row in results]
        except psycopg2.Error as e:
            logger.error(f"Query execution failed: {e}\nQuery: {query}")
            return []

    def fetch_recent_telemetry(
        self, hours: int = 1, device_id: Optional[str] = None
    ) -> pd.DataFrame:
        """
        Fetch recent telemetry data.

        Args:
            hours: How many hours back to fetch (default 1)
            device_id: Specific device ID to fetch, or None for all

        Returns:
            DataFrame with telemetry data.
        """
        if device_id:
            query = f"""
            SELECT * FROM public.{self.table}
            WHERE timestamp > now() - interval '{hours} hours'
            AND device_id = %s
            ORDER BY timestamp DESC
            """
            results = self.execute_query(query, (device_id,))
        else:
            query = f"""
            SELECT * FROM public.{self.table}
            WHERE timestamp > now() - interval '{hours} hours'
            ORDER BY timestamp DESC
            """
            results = self.execute_query(query)

        if not results:
            return pd.DataFrame()

        df = pd.DataFrame(results)
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        return df

    def fetch_anomaly_window_aggregate(
        self, device_id: str, radio: str, window_minutes: int = 5
    ) -> Dict[str, Any]:
        """
        Fetch aggregated metrics using window functions for anomaly detection.

        Args:
            device_id: Device ID to query
            radio: Radio identifier (e.g., "5GHz", "2.4GHz")
            window_minutes: Window size in minutes for aggregation

        Returns:
            Dictionary with aggregated metrics and computed anomaly scores.
        """
        query = f"""
        SELECT
            device_id,
            radio,
            timestamp,
            channel_utilization_pct,
            obss_utilization_pct,
            tx_retries,
            tx_failed,
            avg_rssi_dbm,
            cca_busy_pct,
            same_channel_ap_count,
            -- Window function: average over last N minutes
            AVG(channel_utilization_pct) OVER (
                PARTITION BY device_id, radio
                ORDER BY timestamp
                RANGE BETWEEN interval '{window_minutes} minutes' PRECEDING AND CURRENT ROW
            ) as util_avg_{window_minutes}m,
            -- Window function: calculate deltas (current - previous)
            tx_retries - LAG(tx_retries, 1, 0) OVER (
                PARTITION BY device_id, radio
                ORDER BY timestamp
            ) as tx_retries_delta,
            tx_failed - LAG(tx_failed, 1, 0) OVER (
                PARTITION BY device_id, radio
                ORDER BY timestamp
            ) as tx_failed_delta,
            -- Window function: z-score within last 30 samples
            (tx_retries - AVG(tx_retries) OVER (
                PARTITION BY device_id, radio
                ORDER BY timestamp
                ROWS BETWEEN 30 PRECEDING AND CURRENT ROW
            )) / NULLIF(STDDEV_POP(tx_retries) OVER (
                PARTITION BY device_id, radio
                ORDER BY timestamp
                ROWS BETWEEN 30 PRECEDING AND CURRENT ROW
            ), 0) as tx_retries_zscore,
            -- Min/max for context
            MIN(avg_rssi_dbm) OVER (
                PARTITION BY device_id, radio
                ORDER BY timestamp
                RANGE BETWEEN interval '{window_minutes} minutes' PRECEDING AND CURRENT ROW
            ) as rssi_min_{window_minutes}m,
            MAX(channel_utilization_pct) OVER (
                PARTITION BY device_id, radio
                ORDER BY timestamp
                RANGE BETWEEN interval '{window_minutes} minutes' PRECEDING AND CURRENT ROW
            ) as util_max_{window_minutes}m
        FROM public.{self.table}
        WHERE device_id = %s
        AND radio = %s
        AND timestamp > now() - interval '2 hours'
        ORDER BY timestamp DESC
        LIMIT 1
        """

        results = self.execute_query(query, (device_id, radio))
        return results[0] if results else {}

    def close(self):
        """Alias for disconnect."""
        self.disconnect()

    def __enter__(self):
        """Context manager entry."""
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.disconnect()
