#!/usr/bin/env python3
"""Analyze operator note windows against shadow + CAN frames."""
import csv
import json
import sys
from collections import Counter
from pathlib import Path

# 11-section ExactApply order (centre-outward): L5..L1, C, R1..R5
# Bit hypothesis from decoder/decode_can.py 15-section SR1 table (bits 2-12)
SECTION_BITS = {
    "R5": 2, "R4": 3, "R3": 4, "R2": 5, "R1": 6, "C": 7,
    "L1": 8, "L2": 9, "L3": 10, "L4": 11, "L5": 12,
}
CASCADE_ORDER = ("R5", "R4", "R3", "R2", "R1", "C", "L1", "L2", "L3", "L4", "L5")


def decode_sections(val: int) -> str:
    on = [name for name, bit in SECTION_BITS.items() if val & (1 << bit)]
    off = [name for name, bit in SECTION_BITS.items() if not (val & (1 << bit))]
    return f"ON={','.join(on) or '-'} OFF={','.join(off) or '-'}"


def show_bm(v: str) -> str:
    iv = int(v)
    return f"{iv} (0x{iv:04X}) {decode_sections(iv)}"


def main():
    sess = Path(sys.argv[1])
    frames = list(csv.DictReader(open(sess / "frames.csv", newline="", encoding="utf-8")))
    shadow = list(csv.DictReader(open(sess / "shadow_channels.csv", newline="", encoding="utf-8")))
    t0 = int(frames[0]["timestamp_ms"]) / 1000.0
    t0u = float(shadow[0]["timestamp"])
    dur = int(frames[-1]["timestamp_ms"]) / 1000.0 - t0

    print("=" * 72)
    print(sess.name, f"duration={dur:.1f}s frames={len(frames)}")
    print("=" * 72)

    windows = [
        ("111s manual R5-R3 off, all on, slow", 108, 135),
        ("191-201s speed increase", 188, 205),
        ("221-231s centre raise + auto height", 218, 235),
        ("350-380s headland ASC sequence", 345, 385),
    ]

    for label, lo, hi in windows:
        print(f"\n## {label} (+{lo}-{hi}s)")
        srows = [(float(r["timestamp"]) - t0u, r) for r in shadow if lo <= float(r["timestamp"]) - t0u <= hi]
        last = None
        for t, r in sorted(srows):
            b = r["host_commanded_bitmap"]
            if b != last:
                print(f"  +{t:6.1f}s speed={float(r['speed_kmh']):.1f}  {show_bm(b)}")
                last = b

        frows = [
            (int(r["timestamp_ms"]) / 1000.0 - t0, r)
            for r in frames
            if r["sa_hex"] == "0xD4" and r["pgn_hex"] == "0xCB00"
            and lo <= int(r["timestamp_ms"]) / 1000.0 - t0 <= hi
        ]
        pre = Counter(r["data_hex"][:8] for t, r in frows)
        print(f"  MNC CB00: {len(frows)} frames, top prefixes: {pre.most_common(5)}")

        bhc = [
            (int(r["timestamp_ms"]) / 1000.0 - t0, r)
            for r in frames if r["sa_hex"] == "0x8A"
            and lo <= int(r["timestamp_ms"]) / 1000.0 - t0 <= hi
        ]
        if bhc:
            print(f"  BHC: {len(bhc)} frames, PGNs={dict(Counter(r['pgn_hex'] for t, r in bhc))}")
            last_pgn = {}
            for t, r in sorted(bhc, key=lambda x: x[0]):
                if last_pgn.get(r["pgn_hex"]) != r["data_hex"][:16]:
                    print(f"    +{t:5.1f}s {r['pgn_hex']} {r['data_hex'][:24]}")
                    last_pgn[r["pgn_hex"]] = r["data_hex"][:16]


if __name__ == "__main__":
    main()
