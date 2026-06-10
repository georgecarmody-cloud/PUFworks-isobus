#!/usr/bin/env python3
import csv
import sys
from collections import Counter
from pathlib import Path

sess = Path(sys.argv[1])
rows = list(csv.DictReader(open(sess / "shadow_channels.csv", newline="")))
t0 = float(rows[0]["timestamp"])

print("BITMAP + MASTER TRANSITIONS:")
prev = None
for r in rows:
    b = int(r["grc_ef00_section_bitmap"])
    mo = r["grc_master_on"]
    key = (b, mo)
    t = float(r["timestamp"]) - t0
    if key != prev:
        print(f"  +{t:5.1f}s  bitmap=0x{b:04X} ({b})  master={mo}")
        prev = key

print("\n5s WINDOWS:")
for w in range(0, 30, 5):
    sub = [r for r in rows if w <= float(r["timestamp"]) - t0 < w + 5]
    if not sub:
        continue
    b = Counter(r["grc_ef00_section_bitmap"] for r in sub)
    m = Counter(r["grc_master_on"] for r in sub)
    bmp = [(hex(int(k)), v) for k, v in b.most_common()]
    print(f"  [{w:2d}-{w+5:2d}s] master={dict(m)} bitmap={bmp}")

frames = list(csv.DictReader(open(sess / "frames.csv", newline="")))
ef = [r for r in frames if r["pgn_hex"] == "0xEF00" and r["sa_hex"] == "0xCC"]
print("\nGRC EF00 section payloads:")
for pat in ["4F0B020102020101", "4F0B020102020102", "4F0B02FF0C", "4F0B02FF0D"]:
    n = sum(1 for r in ef if r["data_hex"].startswith(pat))
    print(f"  {pat}: {n}")
print("  4F0B020102 variants:", Counter(r["data_hex"] for r in ef if r["data_hex"].startswith("4F0B020102")))

ef1c = [r for r in frames if r["pgn_hex"] == "0xEF00" and r["sa_hex"] == "0x1C"]
print(f"\n0x1C EF00 n={len(ef1c)} variants={len(set(r['data_hex'] for r in ef1c))}")
for hx, n in Counter(r["data_hex"] for r in ef1c).most_common(8):
    print(f"  {n:4d} {hx}")

# bit decode helper
for val in [65518, 65526, 65510, 65534]:
    cleared = [i for i in range(16) if not (val >> i & 1)]
    print(f"0x{val:04X}: cleared bits {cleared}")
