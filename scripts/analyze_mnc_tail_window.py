#!/usr/bin/env python3
"""Correlate MNC CB00 bytes 4-7 with speed across time windows (ASC / slowdown analysis).

Usage:
  python scripts/analyze_mnc_tail_window.py recordings/20260615_095343_616r_spray_live
  python scripts/analyze_mnc_tail_window.py recordings/<session> --windows 120,190 195,215 220,250
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from gps_bridge_lib import decode_speed_fef1  # noqa: E402


def load_frames(sess: Path) -> tuple[list[dict], float]:
    rows = list(csv.DictReader(open(sess / "frames.csv", newline="", encoding="utf-8")))
    t0 = int(rows[0]["timestamp_ms"]) / 1000.0
    return rows, t0


def row_t(row: dict, t0: float) -> float:
    return int(row["timestamp_ms"]) / 1000.0 - t0


def build_speed_index(rows: list[dict], t0: float) -> list[tuple[float, float]]:
    pts: list[tuple[float, float]] = []
    for r in rows:
        if r["pgn_hex"] != "0xFEF1":
            continue
        s = decode_speed_fef1(r["data_hex"])
        if s is not None:
            pts.append((row_t(r, t0), s))
    pts.sort()
    return pts


def speed_near(pts: list[tuple[float, float]], t: float, window: float = 0.5) -> float | None:
    lo = t - window
    hi = t + window
    speeds = [s for ts, s in pts if lo <= ts <= hi]
    if not speeds:
        return None
    return sum(speeds) / len(speeds)


def u16_le(b: bytes, off: int) -> int:
    return b[off] | (b[off + 1] << 8)


def analyze_window(rows: list[dict], t0: float, lo: float, hi: float, speed_pts: list[tuple[float, float]]) -> dict:
    mnc = [
        r
        for r in rows
        if r["sa_hex"] == "0xD4"
        and r["pgn_hex"] == "0xCB00"
        and lo <= row_t(r, t0) <= hi
    ]
    by_suffix = Counter()
    by_tail4 = Counter()
    by_prefix4 = Counter()
    tail_u16_le: Counter[int] = Counter()
    tail_u16_be: Counter[int] = Counter()
    lane_byte0 = Counter()
    speeds: list[float] = []

    for r in mnc:
        hx = r["data_hex"].upper()
        if len(hx) < 16:
            continue
        b = bytes.fromhex(hx)
        by_prefix4[hx[:8]] += 1
        by_suffix[hx[2:8]] += 1
        tail = hx[8:16]
        by_tail4[tail] += 1
        lane_byte0[f"0x{b[0]:02X}"] += 1
        tail_u16_le[u16_le(b, 4)] += 1
        tail_u16_be[(b[4] << 8) | b[5]] += 1
        t = row_t(r, t0)
        sp = speed_near(speed_pts, t, window=0.5)
        if sp is not None:
            speeds.append(sp)

    avg_sp = round(sum(speeds) / len(speeds), 1) if speeds else None
    min_sp = round(min(speeds), 1) if speeds else None
    max_sp = round(max(speeds), 1) if speeds else None

    return {
        "window_s": [lo, hi],
        "mnc_frames": len(mnc),
        "speed_kmh": {"avg": avg_sp, "min": min_sp, "max": max_sp, "samples": len(speeds)},
        "top_suffix6": [[k, n] for k, n in by_suffix.most_common(8)],
        "top_prefix4": [[k, n] for k, n in by_prefix4.most_common(8)],
        "top_tail4": [[k, n] for k, n in by_tail4.most_common(12)],
        "top_u16_le_b45": [[hex(k), n] for k, n in tail_u16_le.most_common(8)],
        "top_u16_be_b45": [[hex(k), n] for k, n in tail_u16_be.most_common(8)],
        "lane_byte0": dict(lane_byte0.most_common()),
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("session", type=Path)
    ap.add_argument(
        "--windows",
        nargs="+",
        default=["120,190", "195,215", "220,250"],
        help="Window pairs lo,hi in seconds (default: spray_live ASC windows)",
    )
    ap.add_argument("-o", "--output", type=Path, help="Write JSON report")
    args = ap.parse_args()

    rows, t0 = load_frames(args.session)
    speed_pts = build_speed_index(rows, t0)
    windows = []
    for w in args.windows:
        lo, hi = (float(x) for x in w.split(","))
        windows.append(analyze_window(rows, t0, lo, hi, speed_pts))

    report = {
        "session": args.session.name,
        "note": "MNC CB00 bytes 4-7 = tail4 hex; suffix6 = bytes1-3",
        "windows": windows,
    }

    for w in windows:
        lo, hi = w["window_s"]
        sp = w["speed_kmh"]
        print(f"\n=== +{lo:.0f}-{hi:.0f} s  MNC={w['mnc_frames']}  speed={sp.get('avg')} km/h ({sp.get('min')}-{sp.get('max')}) ===")
        print("  suffix6:", ", ".join(f"{k}({n})" for k, n in w["top_suffix6"][:5]))
        print("  tail4 (bytes4-7):", ", ".join(f"{k}({n})" for k, n in w["top_tail4"][:6]))
        print("  u16 LE @4:", ", ".join(f"{k}({n})" for k, n in w["top_u16_le_b45"][:4]))

    out = args.output or ROOT / "library" / f"mnc_tail_{args.session.name}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"\nWrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
