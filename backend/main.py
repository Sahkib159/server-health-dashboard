"""Server Health Dashboard API (FastAPI + SQLite)."""
import os
import secrets
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

DB_PATH = os.getenv("DB_PATH", "health.db")
API_KEY = os.getenv("API_KEY", "dev-key")
RETENTION_HOURS = 24
OFFLINE_AFTER_SECONDS = 30

# Alert rules
CPU_LIMIT = 85            # average CPU %...
CPU_WINDOW_SECONDS = 120  # ...over this window
CPU_MIN_SAMPLES = 3
RAM_LIMIT = 90
DISK_LIMIT = 90

STATIC_DIR = Path(__file__).parent / "static"
app = FastAPI(title="Server Health Dashboard")


# ---------- database ----------
@contextmanager
def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with db() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS metrics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                server TEXT NOT NULL,
                ts REAL NOT NULL,
                cpu REAL, ram REAL, disk REAL,
                net_sent INTEGER, net_recv INTEGER, uptime REAL
            );
            CREATE INDEX IF NOT EXISTS idx_metrics_server_ts ON metrics(server, ts);
            CREATE TABLE IF NOT EXISTS alerts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                server TEXT NOT NULL,
                kind TEXT NOT NULL,
                message TEXT NOT NULL,
                opened REAL NOT NULL,
                resolved REAL
            );
            """
        )


init_db()


# ---------- models ----------
class Metric(BaseModel):
    server: str = Field(min_length=1, max_length=64)
    cpu: float = Field(ge=0, le=100)
    ram: float = Field(ge=0, le=100)
    disk: float = Field(ge=0, le=100)
    net_sent: int = Field(ge=0, default=0)
    net_recv: int = Field(ge=0, default=0)
    uptime: float = Field(ge=0, default=0)


# ---------- alert logic ----------
def set_alert(conn, server: str, kind: str, active: bool, message: str, now: float) -> None:
    """Open an alert if the rule is firing and none is open; resolve it when it clears."""
    open_alert = conn.execute(
        "SELECT id FROM alerts WHERE server=? AND kind=? AND resolved IS NULL", (server, kind)
    ).fetchone()
    if active and not open_alert:
        conn.execute(
            "INSERT INTO alerts (server, kind, message, opened) VALUES (?,?,?,?)",
            (server, kind, message, now),
        )
    elif not active and open_alert:
        conn.execute("UPDATE alerts SET resolved=? WHERE id=?", (now, open_alert["id"]))


def evaluate_alerts(conn, m: Metric, now: float) -> None:
    rows = conn.execute(
        "SELECT cpu FROM metrics WHERE server=? AND ts>=?", (m.server, now - CPU_WINDOW_SECONDS)
    ).fetchall()
    if len(rows) >= CPU_MIN_SAMPLES:
        avg = sum(r["cpu"] for r in rows) / len(rows)
        set_alert(conn, m.server, "cpu", avg > CPU_LIMIT,
                  f"CPU averaged {avg:.0f}% over the last {CPU_WINDOW_SECONDS // 60} minutes", now)
    set_alert(conn, m.server, "ram", m.ram > RAM_LIMIT, f"Memory at {m.ram:.0f}%", now)
    set_alert(conn, m.server, "disk", m.disk > DISK_LIMIT, f"Disk at {m.disk:.0f}% full", now)


# ---------- routes ----------
@app.post("/api/metrics", status_code=201)
def ingest(m: Metric, x_api_key: str = Header(default="")):
    if not secrets.compare_digest(x_api_key, API_KEY):
        raise HTTPException(status_code=401, detail="Invalid or missing X-API-Key header")
    now = time.time()
    with db() as conn:
        conn.execute(
            "INSERT INTO metrics (server, ts, cpu, ram, disk, net_sent, net_recv, uptime) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (m.server, now, m.cpu, m.ram, m.disk, m.net_sent, m.net_recv, m.uptime),
        )
        conn.execute("DELETE FROM metrics WHERE server=? AND ts<?",
                     (m.server, now - RETENTION_HOURS * 3600))
        evaluate_alerts(conn, m, now)
    return {"ok": True}


@app.get("/api/servers")
def servers():
    now = time.time()
    with db() as conn:
        rows = conn.execute(
            "SELECT m.* FROM metrics m JOIN "
            "(SELECT server, MAX(ts) AS mts FROM metrics GROUP BY server) x "
            "ON m.server=x.server AND m.ts=x.mts ORDER BY m.server"
        ).fetchall()
        open_counts = {
            r["server"]: r["n"]
            for r in conn.execute(
                "SELECT server, COUNT(*) AS n FROM alerts WHERE resolved IS NULL GROUP BY server"
            )
        }
    return [
        {
            "server": r["server"],
            "cpu": r["cpu"], "ram": r["ram"], "disk": r["disk"],
            "uptime": r["uptime"],
            "last_seen": r["ts"],
            "online": now - r["ts"] <= OFFLINE_AFTER_SECONDS,
            "open_alerts": open_counts.get(r["server"], 0),
        }
        for r in rows
    ]


@app.get("/api/metrics")
def history(server: str, minutes: int = Query(60, ge=1, le=RETENTION_HOURS * 60)):
    since = time.time() - minutes * 60
    with db() as conn:
        rows = conn.execute(
            "SELECT ts, cpu, ram, disk FROM metrics WHERE server=? AND ts>=? ORDER BY ts",
            (server, since),
        ).fetchall()
    return [dict(r) for r in rows]


@app.get("/api/alerts")
def alerts(server: str | None = None, limit: int = Query(20, ge=1, le=100)):
    query, args = "SELECT * FROM alerts", []
    if server:
        query += " WHERE server=?"
        args.append(server)
    query += " ORDER BY opened DESC LIMIT ?"
    args.append(limit)
    with db() as conn:
        return [dict(r) for r in conn.execute(query, args).fetchall()]


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")