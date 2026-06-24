#!/usr/bin/env python3
import csv
from pathlib import Path

sess = Path(r"C:\Projects\PUFworks-isobus\recordings\20260611_131017_616r_observe_3_long")
frames = list(csv.DictReader(open(sess / "frames.csv", newline="", encoding="utf-8")))
shadow = list(csv.DictReader(open(sess / "shadow_channels.csv", newline="", encoding="utf-8")))
t0 = int(frames[0]["timestamp_ms"]) / 1000.0
t0u = float(shadow[0]["timestamp"])


def summarize(lo, hi, title):
    srows = [(float(r["timestamp"]) - t0u, r) for r in shadow if lo <= float(r["timestamp"]) - t0u <= hi]
    bms = sorted(set(int(r["host_commanded_bitmap"]) for t, r in srows))
    spd = [float(r["speed_kmh"]) for t, r in srows]
    print(f"\n{title}")
    print(f"  speed {min(spd):.1f}-{max(spd):.1f} km/h")
    print(f"  unique bitmaps ({len(bms)}):", ", ".join(f"0x{v:04X}" for v in bms[:16]))
    n_fffe = sum(1 for t, r in srows if int(r["host_commanded_bitmap"]) == 65534)
    n_19 = sum(1 for t, r in srows if int(r["host_commanded_bitmap"]) == 19)
    print(f"  samples: all-on 0xFFFE={n_fffe}  minimal 0x0013={n_19}")


summarize(108, 135, "111s window")
summarize(188, 205, "191-201s speed")
summarize(218, 235, "221-231s boom")
summarize(345, 385, "350-380s headland")

rows = [
    (int(r["timestamp_ms"]) / 1000.0 - t0, r)
    for r in frames
    if r["sa_hex"] == "0x8A" and 218 <= int(r["timestamp_ms"]) / 1000.0 - t0 <= 235
]
rows.sort(key=lambda x: x[0])
last = {}
print("\nBHC 218-235s payload changes:")
for t, r in rows:
    k = r["pgn_hex"]
    if last.get(k) != r["data_hex"]:
        print(f"  +{t:5.1f}s {k} {r['data_hex']}")
        last[k] = r["data_hex"]

for sa in ("0xD4", "0xF7", "0xE1"):
    sub = [
        r for r in frames
        if r["sa_hex"] == sa and r["pgn_hex"] == "0xCB00"
        and 110 <= int(r["timestamp_ms"]) / 1000.0 - t0 <= 112
    ]
    if sub:
        print(f"\nCB00 {sa} at ~111s (first 3):")
        for r in sub[:3]:
            b = bytes.fromhex(r["data_hex"])
            u16 = b[0] | (b[1] << 8) if len(b) >= 2 else 0
            print(f"  {r['data_hex'][:24]}  u16[0:2]=0x{u16:04X}")
