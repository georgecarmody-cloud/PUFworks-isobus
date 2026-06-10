#!/usr/bin/env python3
"""Timeline EF00 payload mix per 10s window for any sniff session."""
import csv
import json
import sys
from collections import Counter
from pathlib import Path

WATCH_PREFIXES = [
    "4F0101", "4F0601", "4F0B02FF0C", "4F0B02FF0D",
    "4F0B020102020101", "4F0B020102020102",
    "4F0B020200050000", "4F0B020201050000",
]


def rate_lha(hx: str):
    if not hx.startswith("4F0101") or len(hx) < 10:
        return None
    b = bytes.fromhex(hx)
    return (b[3] | (b[4] << 8)) / 10.0


def main():
    sess = Path(sys.argv[1])
    meta = json.loads((sess / "session_meta.json").read_text())
    frames = list(csv.DictReader(open(sess / "frames.csv", newline="", encoding="utf-8")))
    ef = [r for r in frames if r["pgn_hex"] == "0xEF00" and r["sa_hex"] == "0xCC"]
    t0 = int(ef[0]["timestamp_ms"]) / 1000.0
    dur = int(ef[-1]["timestamp_ms"]) / 1000.0 - t0
    print(f"{sess.name}  duration={dur:.1f}s  EF00={len(ef)}\n")

    print("RATE CHANGES:")
    prev = None
    for r in ef:
        hx = r["data_hex"]
        if not hx.startswith("4F0101"):
            continue
        raw = bytes.fromhex(hx)[3] | (bytes.fromhex(hx)[4] << 8)
        if raw != prev:
            t = int(r["timestamp_ms"]) / 1000.0 - t0
            print(f"  +{t:5.1f}s  {rate_lha(hx):5.1f} L/ha")
            prev = raw

    print("\n10s WINDOWS:")
    for w in range(0, int(dur) + 1, 10):
        sub = [r for r in ef if w <= int(r["timestamp_ms"]) / 1000.0 - t0 < w + 10]
        if not sub:
            continue
        counts = Counter()
        for r in sub:
            for p in WATCH_PREFIXES:
                if r["data_hex"].startswith(p):
                    counts[p] += 1
        master = Counter(r["data_hex"] for r in sub if r["data_hex"].startswith("4F0601"))
        rates = Counter(rate_lha(r["data_hex"]) for r in sub if rate_lha(r["data_hex"]) is not None)
        print(f"\n[{w:2d}-{w+10:2d}s] n={len(sub)}")
        print(f"  rate: {dict(rates)}")
        print(f"  master: {dict((k[-8:], v) for k, v in master.items())}")
        for p in WATCH_PREFIXES:
            if counts[p]:
                print(f"  {p}: {counts[p]}")

    # shadow if new columns present
    shadow_path = sess / "shadow_channels.csv"
    with open(shadow_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fields = reader.fieldnames or []
        rows = list(reader)
    print(f"\nshadow rows={len(rows)} fields={fields}")
    if rows:
        alive = sum(1 for r in rows if r.get("grc_alive") == "1")
        hosts = Counter(r.get("host_commanded_bitmap", "") for r in rows)
        print(f"  grc_alive={alive}/{len(rows)} host_bitmap={hosts.most_common(3)}")
        if "grc_ef00_rate_l_ha" in fields:
            masters = Counter(r.get("grc_master_on", "") for r in rows)
            bitmaps = Counter(r.get("grc_ef00_section_bitmap", "") for r in rows)
            print(f"  grc_master_on={masters.most_common()}")
            print(f"  grc_section_bitmap={bitmaps.most_common(5)}")


if __name__ == "__main__":
    main()
