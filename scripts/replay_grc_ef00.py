#!/usr/bin/env python3
"""Replay GRC EF00 frames through the live parser and print section transitions."""
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

SECTIONS = ("L1", "L2", "C", "R2", "R1")


def replay(sess: Path):
    ctrl = mod.ISOBUSController()
    ctrl.jdrc_address = 0xCC
    frames = [
        r for r in csv.DictReader(open(sess / "frames.csv", newline="", encoding="utf-8"))
        if r["pgn_hex"] == "0xEF00" and r["sa_hex"] == "0xCC"
    ]
    t0 = int(frames[0]["timestamp_ms"]) / 1000.0
    prev = None
    print(f"REPLAY {sess.name}")
    for r in frames:
        hx = r["data_hex"]
        if not (hx.startswith("4F0B0202") or hx.startswith("4F0601")):
            continue
        ctrl._parse_grc_ef00(0xCC, 0xEF00, bytes.fromhex(hx))
        st = tuple(ctrl.grc_section_enabled[s] for s in SECTIONS)
        key = (st, ctrl.grc_ef00_section_bitmap)
        if key != prev:
            t = int(r["timestamp_ms"]) / 1000.0 - t0
            off = [s for s in SECTIONS if not ctrl.grc_section_enabled[s]]
            print(f"+{t:5.1f}s  mask=0x{ctrl.grc_ef00_section_bitmap:04X}  OFF={off or '-'}")
            prev = key


if __name__ == "__main__":
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(
        r"C:\Users\georg\AppData\Local\Programs\react-example\resources\engine\recordings\20260609_150232_gatest_12"
    )
    replay(path)
