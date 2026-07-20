"""UDP stream packets for full ISOBUS decode over WiFi (bus_engine stdout relay)."""

from __future__ import annotations

import json
import time

SCHEMA_LINE = "IsobusWifiLineV1"
SCHEMA_HEARTBEAT = "CanWifiHeartbeatV1"
DEFAULT_PORT = 5578
DEFAULT_MULTICAST = "239.255.42.1"


def encode_line(kind: str, payload: dict | str) -> bytes:
    msg = {
        "schema": SCHEMA_LINE,
        "ts_ms": int(time.time() * 1000),
        "kind": kind,
        "payload": payload,
    }
    return (json.dumps(msg, separators=(",", ":")) + "\n").encode("ascii")


def encode_heartbeat() -> bytes:
    return (
        json.dumps(
            {"schema": SCHEMA_HEARTBEAT, "ts_ms": int(time.time() * 1000)},
            separators=(",", ":"),
        )
        + "\n"
    ).encode("ascii")


def decode_packet(raw: bytes) -> dict | None:
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None


def is_heartbeat_packet(obj: dict) -> bool:
    return obj.get("schema") == SCHEMA_HEARTBEAT
