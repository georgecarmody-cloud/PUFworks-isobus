#!/usr/bin/env python3
"""Correlate ga_test5 operator script with GRC EF00 payload transitions."""
import csv
from collections import Counter, defaultdict
from pathlib import Path

SESSION = Path(
    r"C:\Users\georg\AppData\Local\Programs\react-example\resources\engine\recordings\20260609_130558_ga_test5"
)

# Operator script (expected ~10s each; session was 77.4s total)
SCRIPT = [
    (0, 10, "1 Master OFF"),
    (10, 20, "2 Master ON"),
    (20, 30, "3 L2 OFF"),
    (30, 40, "4 L2 ON"),
    (40, 50, "5 R2 OFF"),
    (50, 60, "6 R2 ON"),
    (60, 70, "7 Rate 60->20 L/ha"),
    (70, 80, "8 Rate 20->60 L/ha"),
    (80, 90, "9 Master OFF"),
    (90, 93, "10 Master ON → stop"),
]

WATCH = [
    "4F0101",      # rate
    "4F0601",      # master?
    "4F0B02FF0C",  # section element?
    "4F0B02FF0D",
    "4F0B020102020101",
    "4F0B020102020102",
    "4F0B020201050000",
    "4F0B020200050000",
    "4B8100",
]


def rate_lha(hx: str) -> float | None:
    if not hx.startswith("4F0101") or len(hx) < 10:
        return None
    b = bytes.fromhex(hx)
    return (b[3] | (b[4] << 8)) / 10.0  # scale /10 matches 60/20 presets


def main():
    frames = list(csv.DictReader(open(SESSION / "frames.csv", newline="", encoding="utf-8")))
    ef = [r for r in frames if r["pgn_hex"] == "0xEF00" and r["sa_hex"] == "0xCC"]
    t0 = int(ef[0]["timestamp_ms"]) / 1000.0

    print(f"Session duration ~{int(ef[-1]['timestamp_ms'])/1000.0 - t0:.1f}s  ({len(ef)} GRC EF00 frames)\n")
    print("=" * 70)
    print("RATE TRANSITIONS (scale /10 -> L/ha)")
    prev = None
    for r in ef:
        hx = r["data_hex"]
        if not hx.startswith("4F0101"):
            continue
        raw = bytes.fromhex(hx)[3] | (bytes.fromhex(hx)[4] << 8)
        if raw != prev:
            t = int(r["timestamp_ms"]) / 1000.0 - t0
            print(f"  +{t:5.1f}s  {rate_lha(hx):5.1f} L/ha  {hx}")
            prev = raw

    print("\n" + "=" * 70)
    print("10s WINDOWS — dominant EF00 families vs operator script")
    for lo, hi, label in SCRIPT:
        if lo >= 80:
            break  # session ended ~77s
        sub = [
            r for r in ef
            if lo <= int(r["timestamp_ms"]) / 1000.0 - t0 < min(hi, 78)
        ]
        if not sub:
            print(f"\n[{lo:2d}-{hi:2d}s] {label} — no frames")
            continue
        counts = Counter()
        for r in sub:
            hx = r["data_hex"]
            for w in WATCH:
                if hx.startswith(w):
                    counts[w] += 1
        rate_vals = Counter()
        for r in sub:
            rl = rate_lha(r["data_hex"])
            if rl is not None:
                rate_vals[rl] += 1
        master = Counter(r["data_hex"] for r in sub if r["data_hex"].startswith("4F0601"))
        print(f"\n[{lo:2d}-{min(hi,77):2d}s] {label}")
        print(f"  rate: {dict(rate_vals)}")
        print(f"  master: {dict((k[-8:], v) for k, v in master.items())}")
        for w in WATCH:
            if counts[w]:
                print(f"  {w}: {counts[w]}")

    print("\n" + "=" * 70)
    print("PAYLOAD APPEARANCE / DISAPPEARANCE (first & last second seen)")
    payloads = set(r["data_hex"] for r in ef)
    interesting = sorted(
        p for p in payloads
        if p.startswith(("4F0B02", "4F0601", "4F0101", "4B81"))
    )
    for hx in interesting:
        times = sorted(int(r["timestamp_ms"]) / 1000.0 - t0 for r in ef if r["data_hex"] == hx)
        print(f"  {hx}")
        print(f"    n={len(times)}  first=+{times[0]:.1f}s  last=+{times[-1]:.1f}s")


if __name__ == "__main__":
    main()
