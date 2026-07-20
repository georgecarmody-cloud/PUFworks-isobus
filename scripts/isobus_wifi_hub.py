#!/usr/bin/env python3
"""
PUFworks ISOBUS WiFi Hub — full bus_engine decode over UDP.

Topology:
  Tractor CAN → CANable / Pi CAN hat → this hub (laptop or Pi) → WiFi UDP → client(s)

**RX-only by default** (SET_CAN_RX_ONLY:1). OBSERVE authority. Streams:
  - TelemetryV1 @ 10 Hz (node liveness, speed, sections, GRC decode, recorder state)
  - CAN_RX with PGN catalog enrichment (spray library)
  - ISOBUS_LOG lines

Windows — double-click for **native GUI** (reads `isobus_wifi_config.json` beside exe):
  IsobusWifiHub.exe

Headless / Pi (no GUI):
  IsobusWifiHub.exe --console
  python scripts/isobus_wifi_hub.py hub
  python scripts/isobus_wifi_hub.py client --gps

Internal (PyInstaller child process):
  IsobusWifiHub.exe --engine-child
"""
from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent


def app_dir() -> Path:
    """Directory for config.json — beside exe when frozen, repo root in dev."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return REPO_ROOT


def engine_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", REPO_ROOT))
    return REPO_ROOT


def config_path() -> Path:
    return app_dir() / "isobus_wifi_config.json"


def load_config() -> dict:
    path = config_path()
    if not path.is_file():
        default = REPO_ROOT / "deploy" / "windows" / "isobus_wifi_config.json"
        if default.is_file():
            import shutil
            shutil.copy(default, path)
            print(f"[hub] Created default config: {path}", flush=True)
        else:
            return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _log(msg: str) -> None:
    print(f"[hub] {msg}", flush=True)


class _SafeStdio:
    """Wrap stdout/stderr so print(..., flush=True) cannot kill the engine child.

    Windowed PyInstaller on Windows often raises OSError 22 (EINVAL) on flush
    when stdout is a pipe — that was aborting bus_engine before CAN/WiFi started.
    """

    def __init__(self, stream) -> None:
        self._stream = stream

    def write(self, s):
        try:
            if self._stream is not None:
                return self._stream.write(s)
        except OSError:
            return 0
        return 0

    def flush(self) -> None:
        try:
            if self._stream is not None:
                self._stream.flush()
        except OSError:
            pass

    def fileno(self):
        return self._stream.fileno()

    def isatty(self) -> bool:
        return False

    @property
    def encoding(self):
        return getattr(self._stream, "encoding", None) or "utf-8"

    def __getattr__(self, name):
        return getattr(self._stream, name)


def run_engine_child() -> None:
    """PyInstaller subprocess entry — run bus_engine in bundled engine_root."""
    root = engine_root()
    os.chdir(root)
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

    # Ensure printable streams exist (windowed builds may hand us None).
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w", encoding="utf-8", errors="replace")
    else:
        sys.stdout = _SafeStdio(sys.stdout)  # type: ignore[assignment]
    if sys.stderr is None:
        sys.stderr = sys.stdout
    else:
        sys.stderr = _SafeStdio(sys.stderr)  # type: ignore[assignment]

    import bus_engine  # noqa: WPS433

    bus_engine.main()


def enrich_can_rx(frame: dict) -> dict:
    """Add PGN name / category / SA label to raw CAN_RX payload."""
    try:
        from spray_pgn_library import pgn_info  # noqa: WPS433
        from sniff_616r import short_sa_label  # noqa: WPS433

        cid = int(str(frame.get("id", "0x0")), 16)
        if frame.get("is_ext", True):
            pgn = (cid >> 8) & 0x3FFFF
            sa = cid & 0xFF
            pf = (pgn >> 8) & 0xFF
        else:
            pgn = (cid >> 8) & 0xFF
            sa = cid & 0xFF
            pf = pgn
        info = pgn_info(pgn, pf)
        out = dict(frame)
        out["pgn_hex"] = f"0x{pgn:04X}"
        out["sa_hex"] = f"0x{sa:02X}"
        out["sa_label"] = short_sa_label(sa)
        out["pgn_name"] = info.get("name", "")
        out["category"] = info.get("category", "")
        return out
    except Exception:
        return frame


def spawn_engine() -> subprocess.Popen:
    if getattr(sys, "frozen", False):
        cmd = [sys.executable, "--engine-child"]
        cwd = str(engine_root())
    else:
        cmd = [sys.executable, "-u", str(REPO_ROOT / "bus_engine.py")]
        cwd = str(REPO_ROOT)
    kwargs: dict = {
        "stdin": subprocess.PIPE,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.STDOUT,
        "text": True,
        "encoding": "utf-8",
        "errors": "replace",
        "bufsize": 1,
        "cwd": cwd,
    }
    if sys.platform == "win32":
        # Avoid a console flash; child is driven entirely via stdin/stdout pipes.
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    return subprocess.Popen(cmd, **kwargs)


def send_engine(proc: subprocess.Popen, line: str) -> None:
    if proc.stdin and proc.poll() is None:
        proc.stdin.write(line + "\n")
        proc.stdin.flush()


def web_static_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", REPO_ROOT)) / "web" / "phone"
    return REPO_ROOT / "web" / "phone"


def save_config(cfg: dict) -> None:
    path = config_path()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)
        f.write("\n")


def start_phone_web(cfg: dict, state, callbacks=None) -> object | None:
    if not cfg.get("web_enabled", True):
        return None
    from isobus_wifi_web import PhoneWebServer  # noqa: WPS433

    static = web_static_dir()
    if not static.is_dir():
        _log(f"WARNING: phone UI not found at {static}")
        return None
    host = str(cfg.get("web_host", "0.0.0.0"))
    port = int(cfg.get("web_port", 8080))
    info = {
        "can_interface": cfg.get("can_interface", "COM2"),
        "profile": cfg.get("sprayer_profile", "jd_616r"),
        "config_path": str(config_path()),
    }
    server = PhoneWebServer(state, static, host, port, info, callbacks)
    server.start_background()
    _log(f"Dashboard: {server.url}")
    _log(f"Admin UI:  {server.admin_url}")
    return server


def default_recordings_dir() -> Path:
    """Beside the exe when frozen; repo recordings/ in dev."""
    return app_dir() / "recordings"


def setup_engine(proc: subprocess.Popen, cfg: dict) -> None:
    if cfg.get("can_rx_only", True):
        send_engine(proc, "SET_CAN_RX_ONLY:1")
    send_engine(proc, f"SET_CAN_BITRATE:{cfg.get('can_bitrate', 250000)}")
    send_engine(proc, f"SET_CAN_TTY_BAUD:{cfg.get('tty_baud', 115200)}")
    send_engine(proc, f"SET_CAN_INTERFACE:{cfg.get('can_interface', 'COM2')}")
    send_engine(proc, f"SET_SPRAYER_PROFILE:{cfg.get('sprayer_profile', 'jd_616r')}")
    send_engine(proc, f"SET_SNIFF_MODE:{cfg.get('sniff_mode', '616r')}")
    rf = cfg.get("record_filter")
    if rf:
        send_engine(proc, f"SET_RECORD_FILTER:{json.dumps(rf, separators=(',', ':'))}")
    rec_root = str(cfg.get("recordings_dir") or default_recordings_dir())
    send_engine(proc, f"SET_RECORDINGS_ROOT:{rec_root}")
    send_engine(proc, f"SET_CONTROL_AUTHORITY:{cfg.get('authority', 'OBSERVE')}")
    send_engine(proc, "SET_GS_EMITTER:0")
    send_engine(proc, "SET_SPEED_INTERLOCK:0")
    send_engine(proc, "START_CAN")
    time.sleep(1.5)


def restart_engine_can(proc: subprocess.Popen, cfg: dict) -> None:
    send_engine(proc, "STOP_CAN")
    time.sleep(0.4)
    setup_engine(proc, cfg)


class HubRuntime:
    """Mutable hub state shared between engine thread and web admin API."""

    def __init__(self, cfg: dict, live, proc: subprocess.Popen) -> None:
        self.cfg = dict(cfg)
        self.live = live
        self.proc = proc
        self._lock = threading.Lock()
        self._publisher = None
        self._nmea_sock = None
        self._nmea_dest = None
        self._gps_bridge = None
        self._can_rx_max_hz = float(cfg.get("can_rx_max_hz", 50))
        self._stream_can_rx = bool(cfg.get("stream_can_rx", True))
        self._setup_network()
        self._setup_gps()

    def _setup_gps(self) -> None:
        from gps_bridge_lib import GpsBridge, normalize_latlon_mode  # noqa: WPS433

        mode = normalize_latlon_mode(str(self.cfg.get("nmea_latlon_mode", "jd_atx")))
        self.cfg["nmea_latlon_mode"] = mode
        self._gps_bridge = GpsBridge(
            latlon_mode=mode,
            gnss_debug=bool(self.cfg.get("gnss_debug", False)),
        )
        self._nmea_sock = None
        self._nmea_dest = None
        if bool(self.cfg.get("nmea_relay", True)):
            host = self.cfg.get("unicast_client") or self.cfg.get("nmea_udp_host")
            if host:
                port = int(self.cfg.get("nmea_udp_port", 9999))
                self._nmea_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                self._nmea_dest = (str(host), port)
                _log(f"NMEA relay -> {host}:{port}  latlon={mode}")
            else:
                _log(f"GPS decode latlon={mode} (NMEA relay off — no Phone IP)")
        else:
            _log(f"GPS decode latlon={mode} (NMEA relay disabled)")

    def _setup_network(self) -> None:
        from can_wifi_lib import UdpPublisher  # noqa: WPS433

        if self._publisher is not None:
            self._publisher.close()
        port = int(self.cfg.get("udp_port", 5578))
        multicast = self.cfg.get("multicast_group") or None
        unicast = self.cfg.get("unicast_client") or None
        if multicast == "none":
            multicast = None
        self._publisher = UdpPublisher(
            port=port, multicast_group=multicast, unicast_host=unicast
        )

    @property
    def publisher(self):
        return self._publisher

    @property
    def can_rx_interval(self) -> float:
        if self._can_rx_max_hz <= 0:
            return 0.0
        return 1.0 / self._can_rx_max_hz

    @property
    def stream_can_rx(self) -> bool:
        return self._stream_can_rx

    def merge_config(self, patch: dict) -> None:
        from gps_bridge_lib import normalize_latlon_mode  # noqa: WPS433

        with self._lock:
            if "nmea_latlon_mode" in patch:
                patch = dict(patch)
                patch["nmea_latlon_mode"] = normalize_latlon_mode(
                    str(patch.get("nmea_latlon_mode", "jd_atx"))
                )
            self.cfg.update(patch)
            save_config(self.cfg)
            self._can_rx_max_hz = float(self.cfg.get("can_rx_max_hz", 50))
            self._stream_can_rx = bool(self.cfg.get("stream_can_rx", True))
            # Hot-apply decode mode — Save alone used to leave the live bridge on
            # the old mode (j1939 → lon ≈ −90) until a full Apply/restart.
            if self._gps_bridge is not None and "nmea_latlon_mode" in patch:
                self._gps_bridge.latlon_mode = patch["nmea_latlon_mode"]

    def apply_can(self) -> tuple[bool, str]:
        with self._lock:
            try:
                restart_engine_can(self.proc, self.cfg)
                return True, f"CAN applied on {self.cfg.get('can_interface', 'COM2')}"
            except Exception as exc:
                return False, str(exc)

    def restart_can(self) -> tuple[bool, str]:
        return self.apply_can()

    def apply_network(self) -> tuple[bool, str]:
        with self._lock:
            try:
                self._setup_network()
                self._setup_gps()
                mode = self.cfg.get("nmea_latlon_mode", "jd_atx")
                return True, f"UDP + NMEA updated (latlon={mode})"
            except Exception as exc:
                return False, str(exc)

    def apply_record_filter(self) -> tuple[bool, str]:
        with self._lock:
            try:
                send_engine(self.proc, f"SET_SNIFF_MODE:{self.cfg.get('sniff_mode', '616r')}")
                rf = self.cfg.get("record_filter")
                if rf:
                    send_engine(
                        self.proc,
                        f"SET_RECORD_FILTER:{json.dumps(rf, separators=(',', ':'))}",
                    )
                rec_root = str(self.cfg.get("recordings_dir") or default_recordings_dir())
                send_engine(self.proc, f"SET_RECORDINGS_ROOT:{rec_root}")
                return True, f"Record filter applied ({self.cfg.get('sniff_mode', '616r')})"
            except Exception as exc:
                return False, str(exc)

    def start_record(self, label: str = "") -> tuple[bool, str]:
        if self.proc is None or self.proc.poll() is not None:
            return False, "Start the hub first"
        try:
            self.apply_record_filter()
            send_engine(self.proc, f"START_RECORD_SESSION:{label.strip()}")
            return True, f"Recording started ({label or 'session'})"
        except Exception as exc:
            return False, str(exc)

    def stop_record(self) -> tuple[bool, str]:
        if self.proc is None or self.proc.poll() is not None:
            return False, "Hub not running"
        try:
            send_engine(self.proc, "STOP_RECORD_SESSION")
            return True, "Recording stopped"
        except Exception as exc:
            return False, str(exc)

    def handle_can_rx(self, frame: dict, enriched: dict, publisher_send) -> None:
        if self._gps_bridge is None:
            return
        cid = int(str(frame.get("id", "0x0")), 16)
        data_hex = str(frame.get("data", ""))
        data = bytes(int(b, 16) for b in data_hex.split()) if data_hex else b""
        fix = self._gps_bridge.update_from_can_id(cid, data)
        if not fix:
            return
        self.live.push_gps(
            {
                "valid": fix.valid,
                "latitude": fix.latitude,
                "longitude": fix.longitude,
                "speed_kmh": fix.speed_kmh,
                "heading_deg": fix.heading_deg,
                "fix_quality": fix.fix_quality,
                "satellites": fix.satellites,
                "altitude_m": fix.altitude_m,
                "gnss_quality_raw": fix.gnss_quality_raw,
                "source": fix.source,
                "latlon_mode": self._gps_bridge.latlon_mode,
                "ts_ms": fix.ts_ms,
            }
        )
        if fix.valid and self._nmea_sock and self._nmea_dest:
            from gps_bridge_lib import nmea_bundle  # noqa: WPS433

            block = nmea_bundle(fix)
            if block:
                self._nmea_sock.sendto(block, self._nmea_dest)
                self.live.bump_nmea()

    def make_callbacks(self):
        from isobus_wifi_web import HubCallbacks  # noqa: WPS433

        runtime = self

        def _save(patch: dict) -> tuple[bool, str]:
            runtime.merge_config(patch)
            return True, "Config saved"

        return HubCallbacks(
            load_config=lambda: dict(runtime.cfg),
            save_config=_save,
            apply_can=runtime.apply_can,
            restart_can=runtime.restart_can,
            apply_network=runtime.apply_network,
        )


def cmd_hub(cfg: dict) -> int:
    from isobus_wifi_stream import encode_heartbeat, encode_line  # noqa: WPS433
    from isobus_wifi_state import HubLiveState  # noqa: WPS433

    live = HubLiveState()
    proc = spawn_engine()
    runtime = HubRuntime(cfg, live, proc)
    web_server = start_phone_web(runtime.cfg, live, runtime.make_callbacks())

    publisher = runtime.publisher
    _log(
        f"CAN {runtime.cfg.get('can_interface', 'COM2')} @ "
        f"{runtime.cfg.get('can_bitrate', 250000)} — "
        f"profile {runtime.cfg.get('sprayer_profile', 'jd_616r')} "
        f"sniff {runtime.cfg.get('sniff_mode', '616r')}"
    )
    mc = runtime.cfg.get("multicast_group")
    if mc and mc != "none":
        _log(f"UDP multicast {mc}:{runtime.cfg.get('udp_port', 5578)}")
    uc = runtime.cfg.get("unicast_client")
    if uc:
        _log(f"UDP unicast -> {uc}:{runtime.cfg.get('udp_port', 5578)}")
    _log("Starting bus_engine (full ISOBUS decode)...")

    stop = threading.Event()
    last_can_rx = 0.0
    stats = {"telemetry": 0, "can_rx": 0, "log": 0}

    def heartbeat_loop() -> None:
        while not stop.is_set():
            runtime.publisher.send(encode_heartbeat())
            send_engine(proc, "UI_HEARTBEAT")
            time.sleep(1.0)

    def engine_reader() -> None:
        nonlocal last_can_rx
        for raw in proc.stdout:
            line = raw.rstrip("\n")
            if line.startswith("TELEMETRY:"):
                try:
                    payload = json.loads(line[len("TELEMETRY:"):])
                    runtime.publisher.send(encode_line("telemetry", payload))
                    live.push_telemetry(payload)
                    stats["telemetry"] += 1
                except json.JSONDecodeError:
                    pass
            elif line.startswith("CAN_RX:"):
                try:
                    frame = json.loads(line[len("CAN_RX:"):])
                    enriched = enrich_can_rx(frame)
                    # Always feed GPS decode; rate-limit only the WiFi can_rx fan-out.
                    runtime.handle_can_rx(frame, enriched, runtime.publisher.send)
                    if runtime.stream_can_rx:
                        now = time.time()
                        interval = runtime.can_rx_interval
                        if not interval or (now - last_can_rx) >= interval:
                            runtime.publisher.send(encode_line("can_rx", enriched))
                            live.push_frame(enriched)
                            last_can_rx = now
                            stats["can_rx"] += 1
                except json.JSONDecodeError:
                    pass
            elif line.startswith("[ISOBUS_LOG]") or line.startswith("[ISOBUS]"):
                runtime.publisher.send(encode_line("log", line))
                live.push_log(line)
                stats["log"] += 1
                print(line, flush=True)

    threading.Thread(target=heartbeat_loop, daemon=True).start()
    threading.Thread(target=engine_reader, daemon=True).start()

    setup_engine(proc, runtime.cfg)
    if web_server is not None:
        web_server.update_hub_info(
            {
                "can_interface": runtime.cfg.get("can_interface", "COM2"),
                "profile": runtime.cfg.get("sprayer_profile", "jd_616r"),
            }
        )
    _log("Hub running — Ctrl+C to stop")
    last_status = time.time()
    try:
        while proc.poll() is None:
            time.sleep(1.0)
            if time.time() - last_status >= 15.0:
                last_status = time.time()
                snap = live.snapshot()
                _log(
                    f"stream stats: tel={stats['telemetry']} can_rx={stats['can_rx']} "
                    f"log={stats['log']} nmea={snap['stats'].get('nmea_sent', 0)}"
                )
    except KeyboardInterrupt:
        _log("Stopping...")
    finally:
        stop.set()
        if proc.poll() is None:
            send_engine(proc, "STOP_CAN")
            time.sleep(0.3)
            try:
                proc.stdin.close()
            except OSError:
                pass
            proc.wait(timeout=5)
        runtime.publisher.close()
        if runtime._nmea_sock:
            runtime._nmea_sock.close()
        if web_server is not None:
            web_server.shutdown()
    return 0


def cmd_client(cfg: dict, args: argparse.Namespace) -> int:
    from can_wifi_lib import UdpSubscriber  # noqa: WPS433
    from isobus_wifi_stream import decode_packet, is_heartbeat_packet  # noqa: WPS433
    from isobus_wifi_state import HubLiveState  # noqa: WPS433

    port = int(args.port or cfg.get("udp_port", 5578))
    multicast = args.multicast if args.multicast != "none" else None
    if args.multicast is None:
        multicast = cfg.get("multicast_group", "239.255.42.1")
        if multicast == "none":
            multicast = None

    live = HubLiveState()
    web_server = None
    if args.web or cfg.get("web_enabled"):
        if args.web_port:
            cfg = dict(cfg)
            cfg["web_port"] = args.web_port
        web_server = start_phone_web(cfg, live)

    subscriber = UdpSubscriber(bind_host=args.bind, port=port, multicast_group=multicast)
    nmea_sock = None
    nmea_dest = None
    bridge = None
    if args.gps:
        from gps_bridge_lib import GpsBridge, nmea_bundle  # noqa: WPS433

        bridge = GpsBridge(latlon_mode=args.latlon_mode, gnss_debug=args.gnss_debug)
        if args.nmea_udp:
            host, p = _parse_host_port(args.nmea_udp, 9999)
            nmea_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            nmea_dest = (host, p)

    _log(f"Client listening :{port}" + (f" multicast {multicast}" if multicast else ""))
    last_tel = {}
    last_hb = time.time()
    try:
        while True:
            raw = subscriber.recv_one(timeout_s=1.0)
            if raw is None:
                if time.time() - last_hb > 5.0:
                    _log("WARNING: no hub heartbeat")
                continue
            obj = decode_packet(raw)
            if not obj:
                continue
            if is_heartbeat_packet(obj):
                last_hb = time.time()
                continue
            if obj.get("schema") != "IsobusWifiLineV1":
                continue
            kind = obj.get("kind")
            payload = obj.get("payload")
            if kind == "telemetry" and isinstance(payload, dict):
                last_tel = payload
                live.push_telemetry(payload)
                if args.status:
                    nodes = []
                    for k, label in (("gwc_alive", "GWC"), ("src_alive", "SRC"),
                                       ("mnc_alive", "MNC"), ("atx_alive", "ATX")):
                        if payload.get(k):
                            nodes.append(label)
                    _log(
                        f"speed={payload.get('speed_kmh', 0):.1f} km/h "
                        f"nodes={','.join(nodes) or '-'} "
                        f"can={payload.get('can_status', '?')}"
                    )
            elif kind == "can_rx" and isinstance(payload, dict):
                live.push_frame(payload)
                if bridge is not None:
                    cid = int(str(payload.get("id", "0x0")), 16)
                    data_hex = str(payload.get("data", ""))
                    data = bytes(int(b, 16) for b in data_hex.split()) if data_hex else b""
                    fix = bridge.update_from_can_id(cid, data)
                    if fix and fix.valid and nmea_sock and nmea_dest:
                        block = nmea_bundle(fix)
                        if block:
                            nmea_sock.sendto(block, nmea_dest)
            elif kind == "log" and isinstance(payload, str):
                live.push_log(payload)
                if args.verbose:
                    print(payload, flush=True)
    except KeyboardInterrupt:
        _log("Client stopped")
    finally:
        subscriber.close()
        if nmea_sock:
            nmea_sock.close()
        if web_server is not None:
            web_server.shutdown()
    return 0


def _parse_host_port(s: str, default_port: int) -> tuple[str, int]:
    if ":" in s:
        host, port_s = s.rsplit(":", 1)
        return host, int(port_s)
    return s, default_port


def main() -> int:
    if "--engine-child" in sys.argv:
        run_engine_child()
        return 0

    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="command")

    sub.add_parser("hub", help="Run gateway (default if no command)")

    cl = sub.add_parser("client", help="Receive decoded stream on tablet/laptop")
    cl.add_argument("--bind", default="0.0.0.0")
    cl.add_argument("--port", type=int, default=None)
    cl.add_argument("--multicast", default=None, help="239.255.42.1 or none")
    cl.add_argument("--gps", action="store_true", help="Decode ATX GPS -> NMEA UDP")
    cl.add_argument("--nmea-udp", default="127.0.0.1:9999")
    cl.add_argument("--no-nmea-udp", action="store_true")
    cl.add_argument("--latlon-mode", default="jd_atx")
    cl.add_argument("--gnss-debug", action="store_true")
    cl.add_argument("--status", action="store_true", help="Print telemetry summary")
    cl.add_argument("--verbose", action="store_true")
    cl.add_argument("--web", action="store_true", help="Phone dashboard HTTP server")
    cl.add_argument("--web-port", type=int, default=None)

    args = ap.parse_args()
    cfg = load_config()

    if args.command is None or args.command == "hub":
        return cmd_hub(cfg)
    if args.command == "client":
        if args.no_nmea_udp:
            args.nmea_udp = None
        if not args.gps and not args.status and not args.verbose:
            args.gps = True
            args.status = True
        return cmd_client(cfg, args)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
