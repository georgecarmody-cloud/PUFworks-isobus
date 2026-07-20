"""Thread-safe live state for ISOBUS WiFi phone UI."""

from __future__ import annotations

import threading
import time
from collections import deque


class HubLiveState:
    """Latest telemetry + rolling CAN/log buffers for HTTP polling."""

    def __init__(self, max_frames: int = 40, max_logs: int = 30) -> None:
        self._lock = threading.Lock()
        self.telemetry: dict = {}
        self.gps: dict = {}
        self.frames: deque = deque(maxlen=max_frames)
        self.logs: deque = deque(maxlen=max_logs)
        self.last_telemetry_ts = 0.0
        self.last_can_rx_ts = 0.0
        self.last_gps_ts = 0.0
        self.started = time.time()
        self.stats = {"telemetry": 0, "can_rx": 0, "log": 0, "nmea_sent": 0}

    def push_telemetry(self, payload: dict) -> None:
        with self._lock:
            self.telemetry = payload
            self.last_telemetry_ts = time.time()
            self.stats["telemetry"] += 1

    def push_gps(self, fix_dict: dict) -> None:
        with self._lock:
            self.gps = fix_dict
            self.last_gps_ts = time.time()

    def push_frame(self, payload: dict) -> None:
        with self._lock:
            self.frames.appendleft(payload)
            self.last_can_rx_ts = time.time()
            self.stats["can_rx"] += 1

    def push_log(self, line: str) -> None:
        with self._lock:
            self.logs.appendleft({"ts_ms": int(time.time() * 1000), "line": line})
            self.stats["log"] += 1

    def bump_nmea(self) -> None:
        with self._lock:
            self.stats["nmea_sent"] += 1

    def snapshot(self) -> dict:
        with self._lock:
            now = time.time()
            tel_age = (now - self.last_telemetry_ts) if self.last_telemetry_ts else None
            gps_age = (now - self.last_gps_ts) if self.last_gps_ts else None
            can_age = (now - self.last_can_rx_ts) if self.last_can_rx_ts else None
            return {
                "telemetry": dict(self.telemetry),
                "gps": dict(self.gps),
                "telemetry_age_s": round(tel_age, 2) if tel_age is not None else None,
                "gps_age_s": round(gps_age, 2) if gps_age is not None else None,
                "can_rx_age_s": round(can_age, 2) if can_age is not None else None,
                "telemetry_live": tel_age is not None and tel_age < 2.0,
                "gps_live": gps_age is not None and gps_age < 3.0,
                "can_rx_live": can_age is not None and can_age < 5.0,
                "frames": list(self.frames),
                "logs": list(self.logs),
                "stats": dict(self.stats),
                "uptime_s": round(now - self.started, 1),
            }
