#!/usr/bin/env python3
"""
ISOBUS CAN -> WiFi gateway and client (RX-only, lightweight).

Replaces a USB-tethered CAN dongle with UDP over cab WiFi. **OBSERVE / GPS only**
— never used for section actuation (see SAFETY.md).

Gateway (edge — Pi + isolated CAN hat, or Windows + CANable):
  python scripts/isobus_wifi.py gateway --interface can0
  python scripts/isobus_wifi.py gateway --interface COM2 --unicast 192.168.4.2

Client (cab laptop / tablet):
  python scripts/isobus_wifi.py client --gps --nmea-udp 127.0.0.1:9999
  python scripts/isobus_wifi.py client --relay   # CAN_RX lines for bus_engine pipe

Windows standalone (after build):
  dist\\isobus_wifi\\isobus_wifi.exe gateway --interface COM2
  dist\\isobus_wifi\\isobus_wifi.exe client --gps

Pi deploy: see deploy/pi/README.md
"""
from __future__ import annotations

import argparse
import json
import socket
import sys
import time
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from can_wifi_lib import (  # noqa: E402
    DEFAULT_MULTICAST,
    DEFAULT_PORT,
    CanWifiFrame,
    UdpPublisher,
    UdpSubscriber,
    encode_udp_packet,
    is_heartbeat,
    open_can_bus,
    run_gateway_loop,
)

try:
    import can  # noqa: F401

    HAS_CAN = True
except ImportError:
    HAS_CAN = False


def _log(msg: str) -> None:
    print(f"[isobus_wifi] {msg}", flush=True)


def _load_config(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def cmd_gateway(args: argparse.Namespace) -> int:
    if not HAS_CAN:
        _log("python-can required: pip install python-can pyserial")
        return 1

    cfg = {}
    if args.config:
        cfg = _load_config(Path(args.config))

    interface = args.interface or cfg.get("can_interface", "can0")
    bitrate = args.bitrate or int(cfg.get("bitrate", 250_000))
    tty_baud = args.tty_baud or int(cfg.get("tty_baud", 115200))
    port = args.port or int(cfg.get("udp_port", DEFAULT_PORT))
    multicast = args.multicast if args.multicast is not None else cfg.get("multicast_group", DEFAULT_MULTICAST)
    unicast = args.unicast or cfg.get("unicast_client")

    if not multicast and not unicast:
        _log("ERROR: set --multicast and/or --unicast destination")
        return 2

    publisher = UdpPublisher(
        port=port,
        multicast_group=multicast or None,
        unicast_host=unicast,
    )
    _log(f"RX-only gateway: CAN {interface} @ {bitrate} bps")
    if multicast:
        _log(f"UDP multicast {multicast}:{port}")
    if unicast:
        _log(f"UDP unicast -> {unicast}:{port}")

    bus = open_can_bus(interface, bitrate=bitrate, tty_baud=tty_baud)
    try:
        run_gateway_loop(
            bus,
            publisher,
            max_hz=args.max_hz,
            log=_log,
        )
    except KeyboardInterrupt:
        _log("stopped")
    finally:
        bus.shutdown()
        publisher.close()
    return 0


def _parse_host_port(s: str, default_port: int) -> tuple[str, int]:
    if ":" in s:
        host, port_s = s.rsplit(":", 1)
        return host, int(port_s)
    return s, default_port


def cmd_client(args: argparse.Namespace) -> int:
    from gps_bridge_lib import GpsBridge, nmea_bundle  # noqa: WPS433

    port = args.port
    multicast = args.multicast or DEFAULT_MULTICAST
    subscriber = UdpSubscriber(
        bind_host=args.bind,
        port=port,
        multicast_group=multicast if args.multicast != "none" else None,
    )

    nmea_sock = None
    nmea_dest = None
    if args.gps and args.nmea_udp:
        nmea_dest = _parse_host_port(args.nmea_udp, 9999)
        nmea_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    json_sock = None
    json_dest = None
    if args.gps and args.json_udp:
        json_dest = _parse_host_port(args.json_udp, 5577)
        json_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    bridge = GpsBridge(latlon_mode=args.latlon_mode, gnss_debug=args.gnss_debug) if args.gps else None
    _log(f"client listening UDP :{port}" + (f" (multicast {multicast})" if multicast else ""))
    if args.gps:
        _log(f"GPS decode ON -> NMEA {args.nmea_udp or 'off'}")
    if args.relay:
        _log("relay mode: CAN_RX lines on stdout")

    last_hb = time.time()
    last_fix_log = 0.0
    frames = 0
    try:
        while True:
            raw = subscriber.recv_one(timeout_s=1.0)
            if raw is None:
                if time.time() - last_hb > args.stale_s:
                    _log(f"WARNING: no gateway heartbeat for {args.stale_s:.0f}s")
                continue
            if is_heartbeat(raw):
                last_hb = time.time()
                continue
            frame = CanWifiFrame.from_udp_payload(raw)
            if frame is None:
                continue
            frames += 1
            if args.relay:
                print(frame.to_can_rx_line(), flush=True)
            if bridge is not None:
                fix = bridge.update_from_can_id(frame.can_id, frame.data[: frame.dlc])
                if fix and fix.valid:
                    if nmea_sock and nmea_dest:
                        block = nmea_bundle(fix)
                        if block:
                            nmea_sock.sendto(block, nmea_dest)
                    if json_sock and json_dest:
                        json_sock.sendto((fix.to_json() + "\n").encode("utf-8"), json_dest)
                    if args.stdout_nmea:
                        block = nmea_bundle(fix)
                        if block:
                            sys.stdout.buffer.write(block)
                            sys.stdout.buffer.flush()
                    now = time.time()
                    if now - last_fix_log > 5.0:
                        _log(
                            f"fix lat={fix.latitude:.7f} lon={fix.longitude:.7f} "
                            f"spd={fix.speed_kmh or 0:.1f} km/h fixq={fix.fix_quality}"
                        )
                        last_fix_log = now
    except KeyboardInterrupt:
        _log(f"stopped ({frames} CAN frames)")
    finally:
        subscriber.close()
        if nmea_sock:
            nmea_sock.close()
        if json_sock:
            json_sock.close()
    return 0


def cmd_smoke(args: argparse.Namespace) -> int:
    """Loopback smoke: synthetic UDP frames (no CAN hardware)."""
    port = args.port
    publisher = UdpPublisher(port=port, multicast_group=None, unicast_host="127.0.0.1")
    subscriber = UdpSubscriber(bind_host="127.0.0.1", port=port, multicast_group=None)
    seen = 0
    try:
        for i in range(10):
            frame = CanWifiFrame(
                can_id=0x18FEF31C,
                is_extended=True,
                dlc=8,
                data=bytes([i & 0xFF] * 8),
                ts_ms=int(time.time() * 1000),
            )
            publisher.send(encode_udp_packet(frame))
            raw = subscriber.recv_one(timeout_s=0.5)
            if raw and not is_heartbeat(raw) and CanWifiFrame.from_udp_payload(raw):
                seen += 1
    finally:
        subscriber.close()
        publisher.close()

    if seen >= 5:
        _log(f"PASS — received {seen}/10 frames on loopback")
        return 0
    _log(f"FAIL — only {seen}/10 frames received")
    return 1


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = ap.add_subparsers(dest="command", required=True)

    gw = sub.add_parser("gateway", help="CAN RX -> UDP (edge device)")
    gw.add_argument("--config", help="JSON config file (Pi deploy)")
    gw.add_argument("--interface", help="can0, COM2, virtual, pcan")
    gw.add_argument("--bitrate", type=int, default=250_000)
    gw.add_argument("--tty-baud", type=int, default=115200)
    gw.add_argument("--port", type=int, default=DEFAULT_PORT)
    gw.add_argument("--multicast", default=DEFAULT_MULTICAST, help="239.255.42.1 or 'none'")
    gw.add_argument("--unicast", help="Optional unicast client IP")
    gw.add_argument("--max-hz", type=float, default=0, help="Optional rate limit (0=unlimited)")
    gw.set_defaults(func=cmd_gateway)

    cl = sub.add_parser("client", help="UDP -> GPS NMEA and/or CAN_RX relay")
    cl.add_argument("--bind", default="0.0.0.0")
    cl.add_argument("--port", type=int, default=DEFAULT_PORT)
    cl.add_argument("--multicast", default=DEFAULT_MULTICAST, help="Join group or 'none' for unicast-only")
    cl.add_argument("--gps", action="store_true", help="Decode ATX GPS and emit NMEA/JSON")
    cl.add_argument("--relay", action="store_true", help="Print CAN_RX lines to stdout")
    cl.add_argument("--nmea-udp", default="127.0.0.1:9999")
    cl.add_argument("--no-nmea-udp", action="store_true")
    cl.add_argument("--json-udp", default="")
    cl.add_argument("--stdout-nmea", action="store_true")
    cl.add_argument("--latlon-mode", choices=("jd_atx", "j1939", "raw"), default="jd_atx")
    cl.add_argument("--gnss-debug", action="store_true")
    cl.add_argument("--stale-s", type=float, default=5.0, help="Warn if no heartbeat")
    cl.set_defaults(func=cmd_client)

    sm = sub.add_parser("smoke", help="Virtual CAN loopback self-test")
    sm.add_argument("--port", type=int, default=15578)
    sm.set_defaults(func=cmd_smoke)

    args = ap.parse_args()
    if getattr(args, "command", "") == "client" and args.no_nmea_udp:
        args.nmea_udp = None
    if args.command == "gateway" and args.multicast == "none":
        args.multicast = None
    if args.command == "client" and args.multicast == "none":
        args.multicast = None
    if args.command == "client" and not args.gps and not args.relay:
        args.gps = True
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
