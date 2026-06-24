#!/usr/bin/env python3
"""Extract GPS / motion track from a recorder session (frames.csv).

Primary sources on 616R X119 tap (field-confirmed):
  ATX 0x1C  PGN 0xFEF3 (65267) — lat/lon ~5 Hz
  ATX 0x1C  PGN 0xFEE8       — heading, speed, pitch, altitude (TCM)
  ATX 0x1C  PGN 0xFEE6       — roll (bytes 2-3, likely)
  DISP 0xF0 PGN 0xFEF1       — wheel speed rebroadcast ~10 Hz

Output: merged fix CSV (GpsBridge state) for QGIS / pandas; optional GeoJSON.

Validate FEF3 decode against a known field position on first use — JD may
require endian / byte-order tweaks (see --be).
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from gps_bridge_lib import GpsBridge


GPS_PGNS = frozenset({"0xFEF3", "0xFEE8", "0xFEE6", "0xFEF1"})


def extract_track(sess: Path, big_endian: bool, latlon_mode: str) -> list[dict]:
    frames = list(csv.DictReader(open(sess / "frames.csv", newline="", encoding="utf-8")))
    if not frames:
        return []
    t0 = int(frames[0]["timestamp_ms"])
    bridge = GpsBridge(latlon_mode=latlon_mode, big_endian=big_endian)
    rows: list[dict] = []
    for r in frames:
        if r["pgn_hex"] not in GPS_PGNS:
            continue
        if r["pgn_hex"] in ("0xFEF3", "0xFEE8", "0xFEE6") and r["sa_hex"] != "0x1C":
            continue
        ts = int(r["timestamp_ms"])
        fix = bridge.update_from_frame(
            sa_hex=r["sa_hex"],
            pgn_hex=r["pgn_hex"],
            data_hex=r["data_hex"],
            timestamp_ms=ts,
        )
        if not fix or not fix.valid:
            continue
        rows.append({
            "timestamp_ms": ts,
            "t_s": round((ts - t0) / 1000.0, 3),
            "latitude": fix.latitude,
            "longitude": fix.longitude,
            "speed_kmh": fix.speed_kmh if fix.speed_kmh is not None else "",
            "heading_deg": fix.heading_deg if fix.heading_deg is not None else "",
            "pitch_deg": fix.pitch_deg if fix.pitch_deg is not None else "",
            "roll_deg": fix.roll_deg if fix.roll_deg is not None else "",
            "yaw_rate_deg_s": fix.yaw_rate_deg_s if fix.yaw_rate_deg_s is not None else "",
            "altitude_m": fix.altitude_m if fix.altitude_m is not None else "",
        })
    return rows


def write_csv(rows: list[dict], out: Path):
    fields = [
        "timestamp_ms", "t_s", "latitude", "longitude", "speed_kmh",
        "heading_deg", "pitch_deg", "roll_deg", "yaw_rate_deg_s", "altitude_m",
    ]
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def write_geojson(rows: list[dict], out: Path):
    coords = [[r["longitude"], r["latitude"]] for r in rows if r["latitude"] != ""]
    fc = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {"source": "616R ATX FEF3+FEE8", "points": len(coords)},
                "geometry": {"type": "LineString", "coordinates": coords},
            }
        ] if coords else [],
    }
    out.write_text(json.dumps(fc, indent=2), encoding="utf-8")


def summarize(rows: list[dict]):
    print(f"  merged fixes: {len(rows)}")
    if not rows:
        return
    r0, r1 = rows[0], rows[-1]
    print(f"    first: lat={r0['latitude']:.7f} lon={r0['longitude']:.7f} +{r0['t_s']}s")
    print(f"    last:  lat={r1['latitude']:.7f} lon={r1['longitude']:.7f} +{r1['t_s']}s")
    if r0.get("pitch_deg") != "":
        print(f"    pitch: {r0['pitch_deg']} .. {r1['pitch_deg']} deg")
    if r0.get("altitude_m") != "":
        print(f"    altitude_m: {r0['altitude_m']} .. {r1['altitude_m']}")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("session", type=Path, help="recordings/<session_id> folder")
    ap.add_argument("--be", action="store_true", help="big-endian lat/lon")
    ap.add_argument(
        "--latlon-mode",
        choices=("jd_atx", "j1939", "raw"),
        default="jd_atx",
        help="FEF3 decode (default: jd_atx for ATX 0x1C on 616R)",
    )
    ap.add_argument("--geojson", type=Path, help="also write GeoJSON LineString")
    ap.add_argument("-o", "--output", type=Path, help="CSV path (default: <session>/gps_track.csv)")
    args = ap.parse_args()
    sess = args.session
    if not (sess / "frames.csv").exists():
        print(f"Missing {sess / 'frames.csv'}", file=sys.stderr)
        sys.exit(1)

    rows = extract_track(sess, args.be, args.latlon_mode)
    out = args.output or (sess / "gps_track.csv")
    write_csv(rows, out)
    print(f"{sess.name}  ->  {out}  ({len(rows)} rows)")
    summarize(rows)
    if args.geojson:
        write_geojson(rows, args.geojson)
        print(f"  GeoJSON: {args.geojson}")


if __name__ == "__main__":
    main()
