#!/usr/bin/env python3
"""Live GPS bridge: 616R ISOBUS CAN -> NMEA (AgOpenGPS) and/or JSON (custom apps).

AgOpenGPS / AgIO:
  1. AgIO -> Ethernet Setup -> enable UDP (green).
  2. Run this bridge; default sends NMEA to 127.0.0.1:9999 (AgIO listen port).
  3. AgIO UDP Monitor should show $GPGGA / $GPRMC / $GPVTG sentences.
  Alternative: --stdout-nmea piped to a virtual serial port (com0com).

Custom apps:
  --json-udp 127.0.0.1:5577  -> GpsFixV2 JSON lines (incl. pitch/roll/yaw)
  --stdout-json              -> one JSON object per fix (pipe to your program)

Live CAN (CANable COM2, 250 kbps):
  python scripts/gps_bridge.py --interface COM2

Replay bench test from a recording:
  python scripts/gps_bridge.py --replay recordings\\20260611_131017_616r_observe_3_long --speed 5

Import as library:
  from gps_bridge_lib import GpsBridge, nmea_bundle, GpsFix
"""
from __future__ import annotations

import argparse
import csv
import json
import socket
import sys
import time
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from gps_bridge_lib import GpsBridge, nmea_bundle  # noqa: E402

try:
    import can
except ImportError:
    can = None


def parse_host_port(s: str, default_port: int) -> tuple[str, int]:
    if ":" in s:
        host, port_s = s.rsplit(":", 1)
        return host, int(port_s)
    return s, default_port


class UdpSink:
    def __init__(self, host: str, port: int):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.dest = (host, port)

    def send(self, payload: bytes):
        self.sock.sendto(payload, self.dest)

    def close(self):
        self.sock.close()


def emit_fix(
    fix,
    *,
    nmea_udp: UdpSink | None,
    json_udp: UdpSink | None,
    stdout_nmea: bool,
    stdout_json: bool,
):
    if nmea_udp or stdout_nmea:
        block = nmea_bundle(fix)
        if block:
            if nmea_udp:
                nmea_udp.send(block)
            if stdout_nmea:
                sys.stdout.buffer.write(block)
                sys.stdout.buffer.flush()
    if json_udp or stdout_json:
        line = (fix.to_json() + "\n").encode("utf-8")
        if json_udp:
            json_udp.send(line)
        if stdout_json:
            sys.stdout.buffer.write(line)
            sys.stdout.buffer.flush()


def run_replay(path: Path, bridge: GpsBridge, rate_hz: float, args):
    frames = list(csv.DictReader(open(path / "frames.csv", newline="", encoding="utf-8")))
    gps_rows = [
        r for r in frames
        if r["pgn_hex"] in ("0xFEF3", "0xFEE8", "0xFEE6", "0xFEF1", "0xFFFF")
    ]
    if not gps_rows:
        print(f"No GPS rows in {path}", file=sys.stderr)
        return 1
    t0 = int(frames[0]["timestamp_ms"])
    nmea_udp = UdpSink(*parse_host_port(args.nmea_udp, 9999)) if args.nmea_udp else None
    json_udp = UdpSink(*parse_host_port(args.json_udp, 5577)) if args.json_udp else None
    last_emit = 0.0
    print(f"Replay {len(gps_rows)} GPS-related frames from {path.name} @ {rate_hz} Hz emit max")
    interval = 1.0 / max(rate_hz, 1.0)
    try:
        for r in gps_rows:
            ts = int(r["timestamp_ms"])
            fix = bridge.update_from_frame(
                sa_hex=r["sa_hex"],
                pgn_hex=r["pgn_hex"],
                data_hex=r["data_hex"],
                timestamp_ms=ts,
            )
            if fix and fix.valid:
                now = time.time()
                if now - last_emit >= interval:
                    emit_fix(
                        fix,
                        nmea_udp=nmea_udp,
                        json_udp=json_udp,
                        stdout_nmea=args.stdout_nmea,
                        stdout_json=args.stdout_json,
                    )
                    last_emit = now
    except KeyboardInterrupt:
        pass
    finally:
        if nmea_udp:
            nmea_udp.close()
        if json_udp:
            json_udp.close()
    return 0


def run_stdin_can_rx(bridge: GpsBridge, args):
    nmea_udp = UdpSink(*parse_host_port(args.nmea_udp, 9999)) if args.nmea_udp else None
    json_udp = UdpSink(*parse_host_port(args.json_udp, 5577)) if args.json_udp else None
    print("Reading CAN_RX lines from stdin (pipe from bus_engine)", flush=True)
    try:
        for line in sys.stdin:
            line = line.strip()
            if not line.startswith("CAN_RX:"):
                continue
            try:
                frame = json.loads(line[len("CAN_RX:"):])
            except json.JSONDecodeError:
                continue
            fix = bridge.update_from_frame(
                sa_hex=frame.get("sa_hex", ""),
                pgn_hex=frame.get("pgn_hex", ""),
                data_hex=frame.get("data_hex", ""),
                timestamp_ms=frame.get("timestamp_ms"),
            )
            if fix and fix.valid:
                emit_fix(
                    fix,
                    nmea_udp=nmea_udp,
                    json_udp=json_udp,
                    stdout_nmea=args.stdout_nmea,
                    stdout_json=args.stdout_json,
                )
    except KeyboardInterrupt:
        pass
    finally:
        if nmea_udp:
            nmea_udp.close()
        if json_udp:
            json_udp.close()
    return 0


def run_live_can(bridge: GpsBridge, args):
    if can is None:
        print("python-can required: pip install python-can", file=sys.stderr)
        return 1
    channel = args.interface
    bustype = "slcan" if channel.upper().startswith("COM") or "/dev/tty" in channel else "pcan"
    kwargs = {"channel": channel, "bustype": bustype, "bitrate": args.bitrate}
    if bustype == "slcan":
        kwargs["ttyBaudrate"] = args.tty_baud
    print(f"Opening CAN {bustype} {channel} @ {args.bitrate} bps", flush=True)
    nmea_udp = UdpSink(*parse_host_port(args.nmea_udp, 9999)) if args.nmea_udp else None
    json_udp = UdpSink(*parse_host_port(args.json_udp, 5577)) if args.json_udp else None
    bus = can.interface.Bus(**kwargs)
    last_log = 0.0
    try:
        for msg in bus:
            if msg.is_extended_id:
                pgn = (msg.arbitration_id >> 8) & 0x3FFFF
                sa = msg.arbitration_id & 0xFF
            else:
                continue
            if pgn not in (0xFEF3, 0xFEE8, 0xFEE6, 0xFEF1, 0xFFFF):
                continue
            # 0xFFFF GNSS-quality + the position/attitude PGNs are StarFire-only;
            # gate to ATX 0x1C (DISP 0xF0 also emits 0xFFFF with other content).
            if pgn in (0xFEF3, 0xFEE8, 0xFEE6, 0xFFFF) and sa != 0x1C:
                continue
            fix = bridge.update_from_can_id(msg.arbitration_id, bytes(msg.data))
            if fix and fix.valid:
                emit_fix(
                    fix,
                    nmea_udp=nmea_udp,
                    json_udp=json_udp,
                    stdout_nmea=args.stdout_nmea,
                    stdout_json=args.stdout_json,
                )
                now = time.time()
                if now - last_log > 5.0:
                    print(
                        f"[gps] lat={fix.latitude:.7f} lon={fix.longitude:.7f} "
                        f"spd={fix.speed_kmh or 0:.1f} km/h hdg={fix.heading_deg or 0:.0f} "
                        f"pitch={fix.pitch_deg or 0:.1f} roll={fix.roll_deg or 0:.1f} "
                        f"yaw={fix.yaw_rate_deg_s or 0:.1f} alt={fix.altitude_m or 0:.0f}m",
                        flush=True,
                    )
                    last_log = now
    except KeyboardInterrupt:
        print("\n[gps] stopped", flush=True)
    finally:
        bus.shutdown()
        if nmea_udp:
            nmea_udp.close()
        if json_udp:
            json_udp.close()
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--interface", default="COM2", help="Live CAN: COM2 slcan, pcan, virtual")
    ap.add_argument("--bitrate", type=int, default=250000)
    ap.add_argument("--tty-baud", type=int, default=115200)
    ap.add_argument("--replay", type=Path, help="Replay GPS from recordings/<session>/frames.csv")
    ap.add_argument("--replay-speed", type=float, default=5.0, help="Max emit rate during replay (Hz)")
    ap.add_argument("--stdin-can-rx", action="store_true", help="Parse CAN_RX:{json} lines from bus_engine stdin")
    ap.add_argument("--latlon-mode", choices=("jd_atx", "j1939", "raw"), default="jd_atx")
    ap.add_argument("--be", action="store_true", help="Big-endian FEF3 decode")
    ap.add_argument("--nmea-udp", default="127.0.0.1:9999",
                    help="Send NMEA to host:port (AgIO listen port 9999)")
    ap.add_argument("--no-nmea-udp", action="store_true", help="Disable NMEA UDP output")
    ap.add_argument("--json-udp", default="",
                    help="Send GpsFixV2 JSON to host:port (e.g. 127.0.0.1:5577). Default off.")
    ap.add_argument("--stdout-nmea", action="store_true", help="Write NMEA to stdout (pipe to virtual COM)")
    ap.add_argument("--stdout-json", action="store_true", help="Write GpsFixV2 JSON lines to stdout")
    args = ap.parse_args()

    if args.no_nmea_udp:
        args.nmea_udp = None

    bridge = GpsBridge(latlon_mode=args.latlon_mode, big_endian=args.be)

    if args.replay:
        return run_replay(args.replay, bridge, args.replay_speed, args)
    if args.stdin_can_rx:
        return run_stdin_can_rx(bridge, args)
    return run_live_can(bridge, args)


if __name__ == "__main__":
    raise SystemExit(main())
