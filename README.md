# Server Health Dashboard

A small monitoring system: a Python agent collects CPU, memory, and disk usage from a machine and sends it to a FastAPI backend. A web dashboard shows live gauges, usage history, and alerts.

```
[agent/collector.py] --POST /api/metrics--> [FastAPI + SQLite] <--fetch-- [Dashboard (JS + Chart.js)]
```

## Features
- Live CPU, memory, and disk gauges, refreshed every 5 seconds
- History chart (15 min to 24 h) with multiple servers
- Alerts: CPU average above 85% for 2 minutes, memory above 90%, disk above 90%. Alerts resolve on their own.
- Offline detection when a server stops reporting for 30 seconds
- API-key protected ingestion, 24-hour data retention

## Run it (Windows PowerShell)
```powershell
python -m venv venv
venv\Scripts\Activate.ps1
pip install -r requirements.txt

# Terminal 1: backend + dashboard
$env:API_KEY = "choose-a-secret"
uvicorn backend.main:app --reload

# Terminal 2: agent (same API key)
$env:API_KEY = "choose-a-secret"
python agent/collector.py --name my-pc
```
Open http://127.0.0.1:8000. Add more machines by running the agent with a different `--name` and `--url`.

Linux/macOS: activate with `source venv/bin/activate` and use `export API_KEY=...`.

Preview the agent without a backend: `python agent/collector.py --dry-run`

## API
| Method | Path | Description |
|---|---|---|
| POST | `/api/metrics` | Agent submits a sample (needs `X-API-Key`) |
| GET | `/api/servers` | Latest reading, online status, open alert count per server |
| GET | `/api/metrics?server=&minutes=` | History for one server |
| GET | `/api/alerts?server=&limit=` | Recent alerts |

Interactive docs: http://127.0.0.1:8000/docs

## Tech
Python, FastAPI, SQLite, psutil, JavaScript, Chart.js