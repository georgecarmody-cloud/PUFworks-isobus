#!/usr/bin/env python3
"""Decode 616R SRC (SA 0xE1) EF00 rate/pressure from a recorder session."""
import csv
import sys
from collections import Counter
from pathlib import Path


def rate_lha_616r(data_hex: str):
    if not data_hex.startswith("4F0101") or len(data_hex) < 10:
        return None
    b = bytes.fromhex(data_hex)
    return (b[3] | (b[4] << 8)) / 10.0


def main():
    sess = Path(sys.argv[1])
    frames = list(csv.DictReader(open(sess / "frames.csv", newline="", encoding="utf-8")))
    t0 = int(frames[0]["timestamp_ms"]) / 1000.0

    print("SRC 0xE1 rate (4F0101, /10 L/ha) changes:")
    prev = None
    for r in frames:
        if r["sa_hex"] != "0xE1" or r["pgn_hex"] != "0xEF00":
            continue
        hx = r["data_hex"]
        if not hx.startswith("4F0101"):
            continue
        raw = int.from_bytes(bytes.fromhex(hx)[3:5], "little")
        if raw == prev:
            continue
        prev = raw
        t = int(r["timestamp_ms"]) / 1000.0 - t0
        print(f"  +{t:6.1f}s  {raw / 10:.1f} L/ha  {hx}")

    if len(sys.argv) > 2:
        t_lo, t_hi = float(sys.argv[2]), float(sys.argv[3])
        print(f"\nEF00 unique payloads SRC +{t_lo}-{t_hi}s:")
        seen = set()
        for r in frames:
            t = int(r["timestamp_ms"]) / 1000.0 - t0
            if not (t_lo <= t <= t_hi) or r["sa_hex"] != "0xE1" or r["pgn_hex"] != "0xEF00":
                continue
            hx = r["data_hex"]
            if hx in seen:
                continue
            seen.add(hx)
            print(f"  +{t:5.1f}s  {hx[:8]}...  {hx}")


if __name__ == "__main__":
    main()
