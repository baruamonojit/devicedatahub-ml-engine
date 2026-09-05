import os
import psycopg2
from psycopg2.extras import RealDictCursor

def get_conn():
    dsn = os.getenv("TS_DB_DSN")
    if dsn:
        return psycopg2.connect(dsn, cursor_factory=RealDictCursor)
    return psycopg2.connect(
        host=os.getenv("TS_HOST", "localhost"),
        port=int(os.getenv("TS_PORT", 5432)),
        user=os.getenv("TS_USER", "postgres"),
        password=os.getenv("TS_PASS", ""),
        dbname=os.getenv("TS_DB", "postgres"),
        cursor_factory=RealDictCursor,
    )

def fetch_window_features(conn, interval_minutes=5):
    sql = f"""
    WITH current AS (
      SELECT device_id,
        avg(value) FILTER (WHERE ts >= NOW() - interval '%s minutes') as mean5,
        stddev_pop(value) FILTER (WHERE ts >= NOW() - interval '%s minutes') as std5
      FROM measurements
      GROUP BY device_id
    ), previous AS (
      SELECT device_id,
        avg(value) FILTER (WHERE ts >= NOW() - interval '%s minutes' AND ts < NOW() - interval '%s minutes') as mean_prev5
      FROM measurements
      GROUP BY device_id
    )
    SELECT c.device_id, c.mean5, c.std5, (c.mean5 - p.mean_prev5) as trend
    FROM current c
    LEFT JOIN previous p USING (device_id);
    """ % (interval_minutes, interval_minutes, interval_minutes*2, interval_minutes)
    with conn.cursor() as cur:
        cur.execute(sql)
        return cur.fetchall()
