"""Collector agent: reads system metrics with psutil and sends them to the API.

Examples (run from the project root):
    python agent/collector.py --dry-run              # just print metrics (Phase 1)
    python agent/collector.py --name my-laptop       # send to http://127.0.0.1:8000
"""
import argparse
import os
import socket
import time

import psutil
import requests


def collect(name: str) -> dict:
    """Take one snapshot of the machine's health."""
    net = psutil.net_io_counters()
    root = os.path.abspath(os.sep)  # "C:\\" on Windows, "/" on Linux/macOS
    return {
        "server": name,
        "cpu": psutil.cpu_percent(interval=1),  # blocks for 1s to measure
        "ram": psutil.virtual_memory().percent,
        "disk": psutil.disk_usage(root).percent,
        "net_sent": net.bytes_sent,
        "net_recv": net.bytes_recv,
        "uptime": time.time() - psutil.boot_time(),
    }


def main() -> None:
    p = argparse.ArgumentParser(description="Server health collector agent")
    p.add_argument("--name", default=socket.gethostname(), help="name shown on the dashboard")
    p.add_argument("--url", default="http://127.0.0.1:8000", help="dashboard API base URL")
    p.add_argument("--api-key", default=os.getenv("API_KEY", "dev-key"))
    p.add_argument("--interval", type=float, default=5, help="seconds between samples")
    p.add_argument("--dry-run", action="store_true", help="print metrics, do not send")
    args = p.parse_args()

    print(f"Collecting as '{args.name}' every {args.interval}s. Ctrl+C to stop.")
    while True:
        started = time.time()
        m = collect(args.name)
        line = f"CPU {m['cpu']:5.1f}%  RAM {m['ram']:5.1f}%  Disk {m['disk']:5.1f}%"
        if args.dry_run:
            print(line)
        else:
            try:
                r = requests.post(
                    f"{args.url}/api/metrics",
                    json=m,
                    headers={"X-API-Key": args.api_key},
                    timeout=5,
                )
                r.raise_for_status()
                print(f"sent  {line}")
            except requests.RequestException as e:
                print(f"send failed ({e}); will retry")
        time.sleep(max(0, args.interval - (time.time() - started)))


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nStopped.")