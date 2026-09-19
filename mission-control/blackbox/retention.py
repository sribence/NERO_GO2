"""Pruning and incident-promotion logic for the blackbox flight recorder.

Kept separate from the FastAPI wiring in app.py so this is plain, testable
Python: no web-framework imports, just file I/O over the rolling buffer.

Buffer layout (relative to a `buffer_dir`, e.g. blackbox/buffer/):
    rolling.jsonl       -- append-only JSONL telemetry log, one record per
                            line, each record has a "t" (unix timestamp) key.
    frames/<ts>.jpg      -- camera frames, named "<unix_ts_with_ms>.jpg" so
                            the timestamp is recoverable from the filename.

Incidents (relative to an `incidents_dir`, e.g. blackbox/incidents/):
    <id>/rolling.jsonl   -- promoted slice of the telemetry log
    <id>/frames/*.jpg    -- promoted frames covering the same window
    <id>/meta.json       -- reason, created_at, counts

Everything here is pure file I/O so it can be unit-tested (or just poked at
in a REPL) without spinning up uvicorn or a robot backend.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import time
from dataclasses import dataclass

ROLLING_FILENAME = "rolling.jsonl"
FRAMES_DIRNAME = "frames"

_FRAME_TS_RE = re.compile(r"^(\d+(?:\.\d+)?)\.jpg$")


def frame_timestamp(filename: str) -> float | None:
    """Recover the unix timestamp encoded in a frame filename, if any."""
    m = _FRAME_TS_RE.match(filename)
    if not m:
        return None
    return float(m.group(1))


def frame_filename(ts: float) -> str:
    return f"{ts:.3f}.jpg"


@dataclass
class BufferStats:
    total_bytes: int
    log_bytes: int
    frame_bytes: int
    frame_count: int
    oldest_ts: float | None
    newest_ts: float | None


def rolling_log_path(buffer_dir: str) -> str:
    return os.path.join(buffer_dir, ROLLING_FILENAME)


def frames_dir(buffer_dir: str) -> str:
    return os.path.join(buffer_dir, FRAMES_DIRNAME)


def ensure_buffer_dirs(buffer_dir: str) -> None:
    os.makedirs(buffer_dir, exist_ok=True)
    os.makedirs(frames_dir(buffer_dir), exist_ok=True)


def append_record(buffer_dir: str, record: dict) -> None:
    """Append one telemetry record to rolling.jsonl (append-only)."""
    ensure_buffer_dirs(buffer_dir)
    with open(rolling_log_path(buffer_dir), "a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")


def read_all_records(buffer_dir: str) -> list[dict]:
    path = rolling_log_path(buffer_dir)
    if not os.path.exists(path):
        return []
    records: list[dict] = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return records


def list_frames(buffer_dir: str) -> list[tuple[float, str]]:
    """Return [(ts, full_path), ...] for a buffer's frames/ dir, oldest first."""
    d = frames_dir(buffer_dir)
    if not os.path.isdir(d):
        return []
    out: list[tuple[float, str]] = []
    for name in os.listdir(d):
        ts = frame_timestamp(name)
        if ts is not None:
            out.append((ts, os.path.join(d, name)))
    out.sort(key=lambda x: x[0])
    return out


def buffer_stats(buffer_dir: str) -> BufferStats:
    records = read_all_records(buffer_dir)
    log_path = rolling_log_path(buffer_dir)
    log_bytes = os.path.getsize(log_path) if os.path.exists(log_path) else 0
    frames = list_frames(buffer_dir)
    frame_bytes = sum(os.path.getsize(p) for _, p in frames if os.path.exists(p))

    ts_values = [r["t"] for r in records if isinstance(r.get("t"), (int, float))]
    ts_values += [ts for ts, _ in frames]
    oldest = min(ts_values) if ts_values else None
    newest = max(ts_values) if ts_values else None

    return BufferStats(
        total_bytes=log_bytes + frame_bytes,
        log_bytes=log_bytes,
        frame_bytes=frame_bytes,
        frame_count=len(frames),
        oldest_ts=oldest,
        newest_ts=newest,
    )


def _log_bytes_of(records: list[dict]) -> int:
    return sum(len(json.dumps(r).encode("utf-8")) + 1 for r in records)


def prune_buffer(
    buffer_dir: str,
    retention_seconds: float,
    max_bytes: int,
    now: float | None = None,
) -> dict:
    """Enforce a time-based retention window AND a total-size cap.

    Deletes the oldest rolling-log lines and frame files once either limit
    is exceeded, oldest first. Returns a summary dict (useful for logging
    and for tests -- this is the thing to assert against).
    """
    now = now if now is not None else time.time()
    ensure_buffer_dirs(buffer_dir)
    cutoff = now - retention_seconds

    # 1) time-based prune of log lines (missing "t" is kept -- never drop
    #    a record we can't date rather than risk losing something we can).
    records = read_all_records(buffer_dir)
    kept_records = [r for r in records if not isinstance(r.get("t"), (int, float)) or r["t"] >= cutoff]
    removed_time_records = len(records) - len(kept_records)

    # 2) time-based prune of frames -- these are safe to delete outright,
    #    the filename IS the timestamp.
    frames = list_frames(buffer_dir)
    kept_frames = [(ts, p) for ts, p in frames if ts >= cutoff]
    removed_time_frames = [(ts, p) for ts, p in frames if ts < cutoff]
    for _, p in removed_time_frames:
        try:
            os.remove(p)
        except OSError:
            pass

    # 3) size-based prune: walk a combined oldest-first timeline of
    #    surviving log lines + frames, dropping from the oldest end until
    #    total size <= max_bytes.
    removed_size_records = 0
    removed_size_frames = 0
    total = _log_bytes_of(kept_records) + sum(
        os.path.getsize(p) for _, p in kept_frames if os.path.exists(p)
    )
    if max_bytes > 0 and total > max_bytes:
        timeline = [(r.get("t", 0.0), "log", r) for r in kept_records]
        timeline += [(ts, "frame", p) for ts, p in kept_frames]
        timeline.sort(key=lambda x: x[0])

        i = 0
        while total > max_bytes and i < len(timeline):
            _, kind, item = timeline[i]
            if kind == "log":
                if item in kept_records:
                    size = len(json.dumps(item).encode("utf-8")) + 1
                    kept_records.remove(item)
                    removed_size_records += 1
                    total -= size
            else:
                size = os.path.getsize(item) if os.path.exists(item) else 0
                try:
                    os.remove(item)
                except OSError:
                    pass
                kept_frames = [(t, p) for t, p in kept_frames if p != item]
                removed_size_frames += 1
                total -= size
            i += 1

    if removed_time_records or removed_size_records:
        tmp_path = rolling_log_path(buffer_dir) + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            for r in kept_records:
                f.write(json.dumps(r) + "\n")
        os.replace(tmp_path, rolling_log_path(buffer_dir))

    return {
        "removed_log_lines": removed_time_records + removed_size_records,
        "removed_frames": len(removed_time_frames) + removed_size_frames,
        "kept_log_lines": len(kept_records),
        "kept_frames": len(kept_frames),
    }


def promote_incident(
    buffer_dir: str,
    incidents_dir: str,
    reason: str,
    window_seconds: float,
    now: float | None = None,
) -> dict:
    """Copy the last `window_seconds` of buffer contents into a permanent
    incidents/<id>/ folder, BEFORE anything gets a chance to prune them.

    Copies (not moves) -- the rolling buffer keeps recording normally.
    Returns the incident's meta.json contents (also written to disk).
    """
    now = now if now is not None else time.time()
    cutoff = now - window_seconds

    records = [
        r for r in read_all_records(buffer_dir)
        if isinstance(r.get("t"), (int, float)) and r["t"] >= cutoff
    ]
    frames = [(ts, p) for ts, p in list_frames(buffer_dir) if ts >= cutoff]

    safe_reason = re.sub(r"[^a-zA-Z0-9_-]+", "_", reason).strip("_") or "unknown"
    ts_label = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime(now)) + f"_{int((now % 1) * 1000):03d}"
    incident_id = f"{ts_label}_{safe_reason}"
    incident_dir = os.path.join(incidents_dir, incident_id)
    frames_out = os.path.join(incident_dir, FRAMES_DIRNAME)
    os.makedirs(frames_out, exist_ok=True)

    with open(os.path.join(incident_dir, ROLLING_FILENAME), "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")

    copied = 0
    for _, src in frames:
        if os.path.exists(src):
            shutil.copy2(src, os.path.join(frames_out, os.path.basename(src)))
            copied += 1

    meta = {
        "id": incident_id,
        "reason": reason,
        "created_at": now,
        "window_seconds": window_seconds,
        "log_line_count": len(records),
        "frame_count": copied,
    }
    with open(os.path.join(incident_dir, "meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)

    return meta


def list_incidents(incidents_dir: str) -> list[dict]:
    if not os.path.isdir(incidents_dir):
        return []
    out: list[dict] = []
    for name in sorted(os.listdir(incidents_dir)):
        d = os.path.join(incidents_dir, name)
        meta_path = os.path.join(d, "meta.json")
        if not os.path.isdir(d) or not os.path.exists(meta_path):
            continue
        try:
            with open(meta_path, "r", encoding="utf-8") as f:
                meta = json.load(f)
        except (OSError, json.JSONDecodeError):
            continue
        meta["frame_count"] = len(list_frames(d))
        out.append(meta)
    out.sort(key=lambda m: m.get("created_at", 0), reverse=True)
    return out


def get_incident_detail(incidents_dir: str, incident_id: str) -> dict | None:
    # incident_id comes from a URL path segment; keep it confined to the
    # incidents_dir (no path traversal via "..").
    if not incident_id or "/" in incident_id or "\\" in incident_id or ".." in incident_id:
        return None
    d = os.path.join(incidents_dir, incident_id)
    meta_path = os.path.join(d, "meta.json")
    if not os.path.isdir(d) or not os.path.exists(meta_path):
        return None
    with open(meta_path, "r", encoding="utf-8") as f:
        meta = json.load(f)
    log_lines = read_all_records(d)
    frames = [os.path.basename(p) for _, p in list_frames(d)]
    return {**meta, "log_lines": log_lines, "frames": frames}
