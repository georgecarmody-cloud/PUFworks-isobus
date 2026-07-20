"""UDP transport for ISOBUS CAN frames (RX-only WiFi gateway)."""

from __future__ import annotations

import json
import socket
import struct
import time
from dataclasses import dataclass
from typing import Callable, Iterator

SCHEMA = "CanWifiFrameV1"
DEFAULT_PORT = 5578
DEFAULT_MULTICAST = "239.255.42.1"


@dataclass
class CanWifiFrame:
    can_id: int
    is_extended: bool
    dlc: int
    data: bytes
    ts_ms: int

    def to_dict(self) -> dict:
        return {
            "schema": SCHEMA,
            "ts_ms": self.ts_ms,
            "id": f"0x{self.can_id:X}",
            "ext": self.is_extended,
            "dlc": self.dlc,
            "data": " ".join(f"{b:02X}" for b in self.data[: self.dlc]),
        }

    def to_can_rx_line(self) -> str:
        """bus_engine-compatible CAN_RX stdout line."""
        payload = {
            "id": f"0x{self.can_id:X}",
            "is_ext": self.is_extended,
            "dlc": self.dlc,
            "data": " ".join(f"{b:02X}" for b in self.data[: self.dlc]),
            "ts": self.ts_ms / 1000.0,
        }
        return "CAN_RX:" + json.dumps(payload, separators=(",", ":"))

    @classmethod
    def from_can_message(cls, msg) -> CanWifiFrame:
        ts_ms = int(msg.timestamp * 1000) if getattr(msg, "timestamp", None) else int(time.time() * 1000)
        return cls(
            can_id=int(msg.arbitration_id),
            is_extended=bool(msg.is_extended_id),
            dlc=int(msg.dlc),
            data=bytes(msg.data),
            ts_ms=ts_ms,
        )

    @classmethod
    def from_udp_payload(cls, raw: bytes) -> CanWifiFrame | None:
        try:
            obj = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return None
        if obj.get("schema") != SCHEMA:
            return None
        cid = int(str(obj["id"]), 16)
        data_hex = str(obj.get("data", ""))
        data = bytes(int(b, 16) for b in data_hex.split()) if data_hex else b""
        return cls(
            can_id=cid,
            is_extended=bool(obj.get("ext", True)),
            dlc=int(obj.get("dlc", len(data))),
            data=data,
            ts_ms=int(obj.get("ts_ms", int(time.time() * 1000))),
        )


def encode_udp_packet(frame: CanWifiFrame) -> bytes:
    return (json.dumps(frame.to_dict(), separators=(",", ":")) + "\n").encode("ascii")


def encode_heartbeat() -> bytes:
    return (
        json.dumps(
            {"schema": "CanWifiHeartbeatV1", "ts_ms": int(time.time() * 1000)},
            separators=(",", ":"),
        )
        + "\n"
    ).encode("ascii")


def is_heartbeat(raw: bytes) -> bool:
    try:
        obj = json.loads(raw.decode("utf-8"))
        return obj.get("schema") == "CanWifiHeartbeatV1"
    except (UnicodeDecodeError, json.JSONDecodeError):
        return False


class UdpPublisher:
    """Send CAN frames to unicast and/or multicast destinations."""

    def __init__(
        self,
        port: int = DEFAULT_PORT,
        multicast_group: str | None = DEFAULT_MULTICAST,
        unicast_host: str | None = None,
        ttl: int = 1,
    ) -> None:
        self.port = port
        self.multicast_group = multicast_group
        self.unicast_host = unicast_host
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        if multicast_group:
            self._sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, ttl)

    def send(self, payload: bytes) -> None:
        if self.multicast_group:
            self._sock.sendto(payload, (self.multicast_group, self.port))
        if self.unicast_host:
            self._sock.sendto(payload, (self.unicast_host, self.port))

    def close(self) -> None:
        self._sock.close()


class UdpSubscriber:
    """Receive CAN frames from UDP (unicast bind or multicast join)."""

    def __init__(
        self,
        bind_host: str = "0.0.0.0",
        port: int = DEFAULT_PORT,
        multicast_group: str | None = DEFAULT_MULTICAST,
    ) -> None:
        self.port = port
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind((bind_host, port))
        if multicast_group:
            mreq = struct.pack(
                "4s4s",
                socket.inet_aton(multicast_group),
                socket.inet_aton(bind_host if bind_host != "0.0.0.0" else "0.0.0.0"),
            )
            self._sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)

    def recv_one(self, timeout_s: float = 1.0) -> bytes | None:
        self._sock.settimeout(timeout_s)
        try:
            data, _addr = self._sock.recvfrom(4096)
            return data
        except socket.timeout:
            return None

    def iter_packets(self, timeout_s: float = 1.0) -> Iterator[bytes]:
        """Yield one packet per call (legacy helper)."""
        pkt = self.recv_one(timeout_s)
        if pkt is not None:
            yield pkt

    def close(self) -> None:
        self._sock.close()


def open_can_bus(
    interface: str,
    bitrate: int = 250_000,
    tty_baud: int = 115200,
):
    """Open python-can Bus with sensible bustype defaults (RX-only caller)."""
    import can  # noqa: WPS433 — optional dep loaded at runtime

    channel = interface
    upper = channel.upper()
    if upper.startswith("COM") or channel.startswith("/dev/tty"):
        bustype = "slcan"
        kwargs = {"channel": channel, "bustype": bustype, "bitrate": bitrate, "ttyBaudrate": tty_baud}
    elif channel.startswith("can") or channel == "vcan0":
        kwargs = {"channel": channel, "bustype": "socketcan", "bitrate": bitrate}
    elif channel == "virtual":
        kwargs = {"channel": "virtual", "bustype": "virtual", "bitrate": bitrate}
    elif upper.startswith("PCAN"):
        kwargs = {"channel": channel, "bustype": "pcan", "bitrate": bitrate}
    else:
        kwargs = {"channel": channel, "bustype": "slcan", "bitrate": bitrate, "ttyBaudrate": tty_baud}
    return can.interface.Bus(**kwargs)


def run_gateway_loop(
    bus,
    publisher: UdpPublisher,
    *,
    heartbeat_hz: float = 1.0,
    log: Callable[[str], None] | None = None,
    max_hz: float = 0.0,
) -> None:
    """Read CAN (never TX) and publish over UDP."""
    last_hb = 0.0
    last_send = 0.0
    min_interval = 1.0 / max_hz if max_hz > 0 else 0.0
    frames = 0
    while True:
        msg = bus.recv(timeout=0.5)
        now = time.time()
        if now - last_hb >= 1.0 / heartbeat_hz:
            publisher.send(encode_heartbeat())
            last_hb = now
        if msg is None:
            continue
        if min_interval and (now - last_send) < min_interval:
            continue
        frame = CanWifiFrame.from_can_message(msg)
        publisher.send(encode_udp_packet(frame))
        last_send = now
        frames += 1
        if log and frames % 5000 == 0:
            log(f"published {frames} frames")
