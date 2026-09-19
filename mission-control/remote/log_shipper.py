"""remote/log_shipper.py -- ships a compact blackbox summary off-robot.

Standalone script (no FastAPI, no fixed port -- `remote` has none per
CONVENTIONS.md). Meant to run inside the tailscale-connected network
(e.g. as its own container on `network_mode: service:tailscale`, or on the
same bridge network as `blackbox` -- either way it just needs to reach the
blackbox HTTP API and, optionally, a remote endpoint over the tailnet).

Every SHIP_INTERVAL_SECONDS it:
  1. polls the blackbox service's GET /incidents and GET /buffer/status
  2. builds a compact JSON summary
  3. POSTs that summary to REMOTE_LOG_ENDPOINT, if one is configured

If REMOTE_LOG_ENDPOINT is unset (the default -- no real remote endpoint
exists yet), it just logs locally what WOULD have been shipped, so the
whole pipeline is testable/visible without any real remote infrastructure.

Run it directly for a quick check:

    BLACKBOX_URL=http://localhost:9108 SHIP_INTERVAL_SECONDS=10 python log_shipper.py
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone

import requests

PILLAR = "remote"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOGS_DIR = os.path.join(BASE_DIR, "logs")
LOG_PATH = os.path.join(LOGS_DIR, "events.jsonl")
os.makedirs(LOGS_DIR, exist_ok=True)

BLACKBOX_URL = os.environ.get("BLACKBOX_URL", "http://blackbox:9108").rstrip("/")
REMOTE_LOG_ENDPOINT = os.environ.get("REMOTE_LOG_ENDPOINT", "").strip()
SHIP_INTERVAL_SECONDS = float(os.environ.get("SHIP_INTERVAL_SECONDS", "300"))
HTTP_TIMEOUT_SECONDS = float(os.environ.get("HTTP_TIMEOUT_SECONDS", "10"))


def log_event(level: str, msg: str, **extra) -> None:
    """CONVENTIONS.md-format JSONL, also echoed to stdout (this has no
    docker volume of its own guaranteed, so stdout is the primary channel;
    the file is a convenience for local runs)."""
    record = {"t": time.time(), "pillar": PILLAR, "level": level, "msg": msg, **extra}
    line = json.dumps(record)
    print(line, flush=True)
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


def fetch_json(path: str) -> dict | list | None:
    url = f"{BLACKBOX_URL}{path}"
    try:
        resp = requests.get(url, timeout=HTTP_TIMEOUT_SECONDS)
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException as exc:
        log_event("error", "failed to fetch from blackbox", url=url, error=str(exc))
        return None


def build_summary() -> dict | None:
    status = fetch_json("/buffer/status")
    incidents = fetch_json("/incidents")

    if status is None and incidents is None:
        # blackbox unreachable entirely -- nothing to ship this cycle
        return None

    incident_list = incidents.get("incidents", []) if isinstance(incidents, dict) else []
    recent_cutoff = time.time() - SHIP_INTERVAL_SECONDS
    recent_incidents = [
        i for i in incident_list
        if isinstance(i.get("created_at"), (int, float)) and i["created_at"] >= recent_cutoff
    ]

    return {
        "shipped_at": datetime.now(timezone.utc).isoformat(),
        "buffer_status": status,
        "incident_count_total": len(incident_list),
        "incident_count_since_last_ship": len(recent_incidents),
        "recent_incidents": [
            {"id": i.get("id"), "reason": i.get("reason"), "created_at": i.get("created_at")}
            for i in recent_incidents
        ],
    }


def ship(summary: dict) -> None:
    if not REMOTE_LOG_ENDPOINT:
        log_event("info", "no REMOTE_LOG_ENDPOINT configured, would have shipped", summary=summary)
        return

    try:
        resp = requests.post(REMOTE_LOG_ENDPOINT, json=summary, timeout=HTTP_TIMEOUT_SECONDS)
        resp.raise_for_status()
        log_event(
            "info",
            "shipped summary to remote endpoint",
            endpoint=REMOTE_LOG_ENDPOINT,
            status_code=resp.status_code,
            incident_count_since_last_ship=summary["incident_count_since_last_ship"],
        )
    except requests.RequestException as exc:
        log_event("error", "failed to ship summary to remote endpoint", endpoint=REMOTE_LOG_ENDPOINT, error=str(exc))


def main() -> None:
    log_event(
        "info",
        "log_shipper started",
        blackbox_url=BLACKBOX_URL,
        ship_interval_seconds=SHIP_INTERVAL_SECONDS,
        remote_endpoint_configured=bool(REMOTE_LOG_ENDPOINT),
    )
    while True:
        summary = build_summary()
        if summary is not None:
            ship(summary)
        time.sleep(SHIP_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
