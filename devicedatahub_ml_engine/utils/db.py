import os
import psycopg2
from psycopg2.extras import RealDictCursor

from devicedatahub_ml_engine.utils.data import ML_FEATURE_COLUMNS


def get_conn():
    dsn = os.getenv("TS_DB_DSN")
    if dsn:
        return psycopg2.connect(dsn, cursor_factory=RealDictCursor)
    return psycopg2.connect(
        host=os.getenv("TS_HOST", os.getenv("DB_HOST", "localhost")),
        port=int(os.getenv("TS_PORT", os.getenv("DB_PORT", 5432))),
        user=os.getenv("TS_USER", os.getenv("DB_USER", "postgres")),
        password=os.getenv("TS_PASS", os.getenv("DB_PASSWORD", "")),
        dbname=os.getenv("TS_DB", os.getenv("DB_NAME", "telemetry")),
        cursor_factory=RealDictCursor,
    )


def _table_name() -> str:
    return os.getenv("DB_TABLE", os.getenv("TS_TABLE", "telemetry"))


def fetch_window_features(conn, interval_minutes=None):
    """
    Fetch window-aggregated telemetry rows for live inference.

    Returns one row per (device_id, radio) with AVG of ML features over the
    aggregation window. Only includes groups that have a recent update
    within the lookback window (new / updated rows since last poll).

    Env:
      POLL_LOOKBACK_MINUTES  - require a row newer than this (default 2)
      WINDOW_MINUTES         - aggregation window size (default 5)
      DB_TABLE / TS_TABLE    - table name (default telemetry)
    """
    lookback = int(
        interval_minutes
        if interval_minutes is not None
        else os.getenv("POLL_LOOKBACK_MINUTES", "2")
    )
    window = int(os.getenv("WINDOW_MINUTES", "5"))
    table = _table_name()

    avg_exprs = ",\n      ".join(f"AVG({col}) AS {col}" for col in ML_FEATURE_COLUMNS)

    sql = f"""
    SELECT
      device_id,
      radio,
      MAX(timestamp) AS timestamp,
      {avg_exprs}
    FROM public.{table}
    WHERE timestamp > NOW() - INTERVAL '{window} minutes'
    GROUP BY device_id, radio
    HAVING MAX(timestamp) > NOW() - INTERVAL '{lookback} minutes'
    ORDER BY device_id, radio;
    """

    with conn.cursor() as cur:
        cur.execute(sql)
        return cur.fetchall()
