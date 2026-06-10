#!/usr/bin/env python3
"""Replay EF00 through parser; sample state at each shadow row timestamp."""
import csv
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))
spec = importlib.util.spec_from_file_location("engine", ROOT / "python" / "engine.py")
mod = importlib.util.module_from_spec(spec)
sys.modules["engine"] = mod
spec.loader.exec_module(mod)

GRC_BITS = {"L1": 1, "L2": 2, "C": 3, "R2": 4, "R1": 5}


def on_list(mask):
    return [n for n, bit in GRC_BITS.items() if mask & (1 << bit)]


def replay(sess: Path):
    ctrl = mod.ISOBUSController()
    ctrl.jdrc_address = 0xCC
    ctrl.sprayer_profile = ctrl.PROFILE_GOLDACRES_GRC

    frames = [
        r for r in csv.DictReader(open(sess / "frames.csv", newline="", encoding="utf-8"))
        if r["pgn_hex"] == "0xEF00" and r["sa_hex"] == "0xCC"
    ]
    shadow = list(csv.DictReader(open(sess / "shadow_channels.csv", newline="", encoding="utf-8")))
    t0 = float(shadow[0]["timestamp"])

    # Build (wall_ts_approx, frame) list — frames use timestamp_ms (epoch ms)
    ef_events = []
    for r in frames:
        hx = r["data_hex"]
        if hx.startswith("4F0B0202") or hx.startswith("4F0601"):
            ts = int(r["timestamp_ms"]) / 1000.0
            ef_events.append((ts, hx))

    fi = 0
    mism = 0
    print(f"REPLAY@SHADOW {sess.name}")
    for row in shadow:
        ts = float(row["timestamp"])
        while fi < len(ef_events) and ef_events[fi][0] <= ts:
            _, hx = ef_events[fi]
            ctrl._parse_grc_ef00(0xCC, 0xEF00, bytes.fromhex(hx))
            fi += 1
        logged = int(row["grc_ef00_section_bitmap"])
        parsed = ctrl.grc_ef00_section_bitmap
        t = ts - t0
        if logged != parsed:
            mism += 1
            print(
                f"MISMATCH +{t:5.1f}s  shadow=0x{logged:04X}{on_list(logged)} "
                f"replay=0x{parsed:04X}{on_list(parsed)} master_log={row['grc_master_on']}"
            )
    print(f"total mismatches: {mism}/{len(shadow)}")


if __name__ == "__main__":
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(
        r"C:\Users\georg\AppData\Local\Programs\react-example\resources\engine\recordings\20260609_174841_gatest_a1"
    )
    replay(path)
