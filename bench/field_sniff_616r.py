"""
Field launcher — 616R integrated CAN sniff (OBSERVE only, zero TX).

Runs bus_engine.py with jd_616r profile, expanded sniff roster, and optional
session recorder. Safe for cab laptop beside image capture — does not ARM or
raise authority above OBSERVE.

Examples:
  python bench/field_sniff_616r.py --interface pcan --label 616r_spray_am
  python bench/field_sniff_616r.py --interface auto --sniff-mode 616r_full --record
  python bench/field_sniff_616r.py --interface pcan --duration 600 --record

After the session:
  python scripts/analyze_616r_session.py recordings/<session_id>
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import threading
import time

ENGINE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "bus_engine.py")

latest_telemetry: dict = {}
telemetry_lock = threading.Lock()


def reader(proc):
    for raw in proc.stdout:
        line = raw.rstrip("\n")
        if line.startswith("TELEMETRY:"):
            try:
                t = json.loads(line[len("TELEMETRY:"):])
                with telemetry_lock:
                    latest_telemetry.clear()
                    latest_telemetry.update(t)
            except json.JSONDecodeError:
                pass
        elif line.startswith("[ISOBUS_LOG]"):
            print(line)


def send(proc, line: str) -> bool:
    try:
        if proc.stdin is None or proc.poll() is not None:
            return False
        proc.stdin.write(line + "\n")
        proc.stdin.flush()
        return True
    except (OSError, ValueError, BrokenPipeError):
        return False


def tel(key, default=None):
    with telemetry_lock:
        return latest_telemetry.get(key, default)


def main():
    ap = argparse.ArgumentParser(description="616R field CAN sniff launcher (OBSERVE)")
    ap.add_argument("--interface", default="COM2",
                    help="CAN interface: COM2 (CANable slcan), pcan, auto, ixxat, can0, or virtual")
    ap.add_argument("--allow-tx", action="store_true",
                    help="Disable RX-only seal (NOT for live implement bus sniff)")
    ap.add_argument("--sniff-mode", default="spray",
                    choices=["filtered", "spray", "616r", "616r_full"],
                    help="spray = library PGNs + spray nodes (default); 616r_full = every frame")
    ap.add_argument("--label", default="", help="Recorder session label suffix")
    ap.add_argument("--record", action="store_true", help="START_RECORD_SESSION on boot")
    ap.add_argument("--duration", type=float, default=0,
                    help="Stop after N seconds (0 = until Ctrl+C)")
    ap.add_argument("--bitrate", type=int, default=250000,
                    help="CAN bus bitrate (616 implement = 250000)")
    ap.add_argument("--tty-baud", type=int, default=115200,
                    help="USB-serial baud for slcan/CANable (try 115200 or 921600)")
    args = ap.parse_args()

    print("[field] PUFworks 616R sniff — OBSERVE only (no CAN TX)")
    print(f"[field] interface={args.interface} sniff_mode={args.sniff_mode} record={args.record}")

    proc = subprocess.Popen(
        [sys.executable, "-u", ENGINE],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, bufsize=1,
        cwd=os.path.dirname(ENGINE),
    )
    threading.Thread(target=reader, args=(proc,), daemon=True).start()

    def setup():
        if not args.allow_tx:
            send(proc, "SET_CAN_RX_ONLY:1")
        send(proc, f"SET_CAN_BITRATE:{args.bitrate}")
        send(proc, f"SET_CAN_TTY_BAUD:{args.tty_baud}")
        send(proc, f"SET_CAN_INTERFACE:{args.interface}")
        send(proc, "SET_SPRAYER_PROFILE:jd_616r")
        send(proc, f"SET_SNIFF_MODE:{args.sniff_mode}")
        send(proc, "SET_CONTROL_AUTHORITY:OBSERVE")
        send(proc, "SET_GS_EMITTER:0")
        send(proc, "SET_SPEED_INTERLOCK:0")  # sniffing at standstill / yard is fine
        send(proc, "START_CAN")
        time.sleep(1.5)
        if args.record:
            cmd = "START_RECORD_SESSION"
            if args.label:
                cmd += f":{args.label}"
            send(proc, cmd)

    setup()

    # UI heartbeat keeps rx/ui interlocks happy if authority is raised later; harmless at OBSERVE
    stop = threading.Event()

    def heartbeat():
        while not stop.is_set():
            send(proc, "UI_HEARTBEAT")
            time.sleep(1.0)

    threading.Thread(target=heartbeat, daemon=True).start()

    t0 = time.time()
    last_status = 0.0
    try:
        while True:
            time.sleep(0.5)
            if args.duration and (time.time() - t0) >= args.duration:
                print("[field] duration reached — stopping")
                break
            if time.time() - last_status >= 10.0:
                last_status = time.time()
                nodes = []
                for key, label in (("gwc_alive", "GWC"), ("src_alive", "SRC"), ("mnc_alive", "MNC")):
                    if tel(key):
                        nodes.append(label)
                rec = tel("record_session_active")
                fc = tel("record_frame_count", 0)
                spd = tel("speed_kmh", 0)
                tx = tel("tx_counts", {}) or {}
                blocked = tel("tx_blocked_count", 0)
                sealed = tel("can_rx_only", True)
                adapter = tel("can_bus_open", False)
                linked = tel("isobus_is_connected", False)
                cst = tel("can_status", "?")
                print(
                    f"[field] +{time.time() - t0:5.0f}s  can={cst} adapter={adapter} traffic={linked}  "
                    f"speed={spd:.1f} km/h  nodes={','.join(nodes) or '-'}  "
                    f"{'REC ' + str(tel('record_session_id', '')) if rec else 'idle'}  frames={fc}  "
                    f"rx_only={sealed} tx={sum((tx or {}).values())}"
                )
    except KeyboardInterrupt:
        print("\n[field] Ctrl+C — stopping recorder and engine")
    finally:
        stop.set()
        if proc.poll() is None:
            if tel("record_session_active"):
                send(proc, "STOP_RECORD_SESSION")
                time.sleep(0.5)
            send(proc, "STOP_CAN")
            time.sleep(0.3)
            try:
                if proc.stdin:
                    proc.stdin.close()
            except OSError:
                pass
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()

    rec_dir = tel("record_dir")
    if rec_dir:
        print(f"[field] Recording: {rec_dir}")
        print(f"[field] Analyze: python scripts/analyze_616r_session.py \"{rec_dir}\"")


if __name__ == "__main__":
    main()
