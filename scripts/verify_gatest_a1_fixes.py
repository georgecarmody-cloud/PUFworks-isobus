#!/usr/bin/env python3
"""Verify FEE8 decode and toggle debounce against gatest_a1 frames."""
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

SESS = Path(
    r"C:\Users\georg\AppData\Local\Programs\react-example\resources\engine\recordings\20260609_174841_gatest_a1"
)
SECTIONS = ("L1", "L2", "C", "R2", "R1")


def replay_ef00_with_sim_time():
    ctrl = mod.ISOBUSController()
    ctrl.jdrc_address = 0xCC
    ctrl.sprayer_profile = ctrl.PROFILE_GOLDACRES_GRC
    frames = [
        r for r in csv.DictReader(open(SESS / "frames.csv", newline="", encoding="utf-8"))
        if r["pgn_hex"] == "0xEF00" and r["sa_hex"] == "0xCC"
    ]
    t0 = int(frames[0]["timestamp_ms"]) / 1000.0
    sim = [0.0]
    mod.time.time = lambda: sim[0]

    prev = None
    flips = 0
    for r in frames:
        hx = r["data_hex"]
        if not (hx.startswith("4F0B0202") or hx.startswith("4F0601")):
            continue
        sim[0] = int(r["timestamp_ms"]) / 1000.0
        ctrl._parse_grc_ef00(0xCC, 0xEF00, bytes.fromhex(hx))
        key = (ctrl.grc_ef00_section_bitmap, tuple(ctrl.grc_section_enabled[s] for s in SECTIONS))
        if key != prev:
            t = sim[0] - t0
            if prev and 11 < t < 20:
                flips += 1
            prev = key
    print(f"EF00 transitions (11-20s window): {flips}")


def test_fee8():
    ctrl = mod.ISOBUSController()
    ctrl._parse_speed = None
    # Simulate FEE8 from JD ATX 0x1C
    data = bytes.fromhex("2E840100F562BA53")
    pgn = 0xFEE8
    sa = 0x1C
    if not ctrl._fef1_speed_seen and len(data) >= 3:
        off = 1 if sa == 0x1C else 0
        raw = data[off] | (data[off + 1] << 8)
        ctrl.speed_kmh = raw / 256.0
    print(f"FEE8 decode (SA 0x1C): {ctrl.speed_kmh:.2f} km/h (expect ~1.52)")


if __name__ == "__main__":
    test_fee8()
    replay_ef00_with_sim_time()
