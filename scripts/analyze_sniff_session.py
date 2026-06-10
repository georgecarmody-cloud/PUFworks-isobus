#!/usr/bin/env python3
"""Quick analyzer for PUFVision OBSERVE session recordings."""
import csv
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path


def analyze(sess: Path):
    meta = json.loads((sess / "session_meta.json").read_text())
    print("=" * 60)
    print(sess.name)
    print(json.dumps(meta, indent=2))

    frames = list(csv.DictReader(open(sess / "frames.csv", newline="", encoding="utf-8")))
    ef = [r for r in frames if r["pgn_hex"] == "0xEF00" and r["sa_hex"] == "0xCC"]
    t0 = int(ef[0]["timestamp_ms"]) / 1000.0 if ef else 0

    print(f"\nframes={len(frames)}  GRC EF00={len(ef)}  unique EF00={len(set(r['data_hex'] for r in ef))}")
    print("Top PGNs:", Counter(r["pgn_hex"] for r in frames).most_common(8))

    payloads = Counter(r["data_hex"] for r in ef)
    print("\nEF00 payloads:")
    for hx, n in payloads.most_common():
        print(f"  n={n:4d} {hx}")

    # Rate timeline
    print("\nRate (4F0101) changes:")
    prev = None
    for r in ef:
        hx = r["data_hex"]
        if not hx.startswith("4F0101"):
            continue
        b = bytes.fromhex(hx)
        raw = b[3] | (b[4] << 8)
        if raw != prev:
            t = int(r["timestamp_ms"]) / 1000.0 - t0
            print(f"  +{t:5.1f}s  {raw / 100:.2f} L/ha  {hx}")
            prev = raw

    # Master-ish 4F0601
    print("\n4F0601 variants:")
    variants = defaultdict(list)
    for r in ef:
        if r["data_hex"].startswith("4F0601"):
            variants[r["data_hex"]].append(int(r["timestamp_ms"]) / 1000.0 - t0)
    for hx, times in sorted(variants.items()):
        print(f"  {hx}  n={len(times)}  first=+{times[0]:.1f}s  last=+{times[-1]:.1f}s")

    # Section-ish 4F0B02FF
    print("\n4F0B02FF* (possible section elements):")
    for hx, n in Counter(r["data_hex"] for r in ef if r["data_hex"].startswith("4F0B02FF")).most_common():
        print(f"  n={n:4d} {hx}")

    # CB00
    cb = [r for r in frames if r["pgn_hex"] == "0xCB00"]
    print(f"\nCB00: {len(cb)} frames, unique={len(set(r['data_hex'] for r in cb))}")
    for hx, n in Counter(r["data_hex"] for r in cb).most_common():
        b = bytes.fromhex(hx)
        u16 = b[0] | (b[1] << 8) if len(b) >= 2 else 0
        print(f"  n={n} u16={u16:#06x} {hx}")

    shadow = list(csv.DictReader(open(sess / "shadow_channels.csv", newline="", encoding="utf-8")))
    print(f"\nshadow: host_bitmap={Counter(r['host_commanded_bitmap'] for r in shadow).most_common()}")
    print(f"        grc_alive={sum(1 for r in shadow if r['grc_alive']=='1')}/{len(shadow)}")


if __name__ == "__main__":
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(
        r"c:\Users\georg\AppData\Local\Programs\react-example\resources\engine\recordings\20260609_125553_ga_test4"
    )
    analyze(path)
