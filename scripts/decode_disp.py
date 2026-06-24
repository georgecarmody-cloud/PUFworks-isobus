#!/usr/bin/env python3
"""Catalog John Deere display (DISP) encodings from a recorder session.

Targets:
  SA 0xF0 — cab terminal rebroadcast (EF00, FFF8, FFF4, FEF1, …)
  SA 0x26 — VT transport (E600 multipacket, …)

Usage:
  python scripts/decode_disp.py recordings/20260615_095343_616r_spray_live
  python scripts/decode_disp.py recordings/<session> --window 195 215
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LIB = ROOT / "library"

# Field-validated / likely (extend with session evidence)
DISP_EF00_KNOWN = {
    "F107CC": {"status": "likely", "role": "grc_link_status", "notes": "~10 Hz; suffix 0000; 0xCC = GRC SA"},
    "F10FFF": {"status": "likely", "role": "display_heartbeat", "notes": "~10 Hz F10FFFFF… stable tail"},
    "F002CC": {"status": "likely", "role": "tc_grc_presence", "notes": "3030FFFF pattern; pairs with F107CC"},
    "F00E88": {"status": "hypothesis", "role": "ui_state_block", "notes": "62 frames/session bursts"},
    "F00888": {"status": "hypothesis", "role": "ui_state_block", "notes": "62 frames/session bursts"},
}

DISP_FFF8_KNOWN = {
    "850400": {"status": "likely", "role": "display_static_a", "notes": "850400FF… ~10 Hz dominant"},
    "9B007D": {"status": "hypothesis", "role": "display_metric_b", "notes": "9B007D00… ~5 Hz"},
}

DISP_E600_KNOWN = {
    "A83C04": {"status": "likely", "role": "vt_transport_chunk", "notes": "A8xx0400 family — VT multipacket to TC"},
    "A83E04": {"status": "likely", "role": "vt_transport_chunk", "notes": "High churn during spray UI updates"},
    "A83D04": {"status": "likely", "role": "vt_transport_chunk", "notes": ""},
    "A80804": {"status": "likely", "role": "vt_transport_chunk", "notes": "Lower rate baseline"},
    "A84C14": {"status": "hypothesis", "role": "vt_object_pool", "notes": "A8xx1400 subfamily ~613 frames"},
}


def load_frames(sess: Path) -> tuple[list[dict], float]:
    rows = list(csv.DictReader(open(sess / "frames.csv", newline="", encoding="utf-8")))
    t0 = int(rows[0]["timestamp_ms"]) / 1000.0
    return rows, t0


def in_window(row: dict, t0: float, lo: float | None, hi: float | None) -> bool:
    if lo is None and hi is None:
        return True
    t = int(row["timestamp_ms"]) / 1000.0 - t0
    if lo is not None and t < lo:
        return False
    if hi is not None and t > hi:
        return False
    return True


def prefix(hx: str, nbytes: int) -> str:
    hx = hx.upper()
    n = nbytes * 2
    return hx[:n] if len(hx) >= n else hx


def catalog_pgn(rows: list[dict], sa: str, pgn: str, nbytes: int, known: dict) -> dict:
    sub = [r for r in rows if r["sa_hex"] == sa and r["pgn_hex"] == pgn]
    by_pre = Counter(prefix(r["data_hex"], nbytes) for r in sub)
    samples = {}
    for r in sub:
        p = prefix(r["data_hex"], nbytes)
        if p not in samples:
            samples[p] = r["data_hex"].upper()
    catalog = []
    total = sum(by_pre.values())
    for p, n in by_pre.most_common(40):
        meta = known.get(p, {})
        catalog.append({
            "prefix": p,
            "frames": n,
            "pct": round(100.0 * n / max(total, 1), 2),
            "sample": samples.get(p, ""),
            "status": meta.get("status", "unknown"),
            "role": meta.get("role", "unclassified"),
            "notes": meta.get("notes", ""),
        })
    return {
        "sa_hex": sa,
        "pgn_hex": pgn,
        "frame_count": total,
        "unique_prefixes": len(by_pre),
        "catalog": catalog,
    }


def mnc_window_diff(rows: list[dict], t0: float, lo: float, hi: float) -> dict:
    mnc = [
        r for r in rows
        if r["sa_hex"] == "0xD4" and r["pgn_hex"] == "0xCB00" and in_window(r, t0, lo, hi)
    ]
    suffix = Counter(r["data_hex"][2:8].upper() for r in mnc if len(r["data_hex"]) >= 8)
    lane = Counter(r["data_hex"][:2].upper() for r in mnc if len(r["data_hex"]) >= 2)
    pre4 = Counter(r["data_hex"][:8].upper() for r in mnc if len(r["data_hex"]) >= 8)
    asc_suffixes = {k: v for k, v in suffix.items() if k.startswith("00A")}
    return {
        "window_t_s": [lo, hi],
        "frames": len(mnc),
        "suffix_top": suffix.most_common(12),
        "asc_suffixes": sorted(asc_suffixes.items(), key=lambda x: -x[1]),
        "lane_top": lane.most_common(12),
        "prefix4_top": pre4.most_common(12),
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("session", type=Path)
    ap.add_argument("--window", nargs=2, type=float, metavar=("T_LO", "T_HI"),
                    help="Optional time window (seconds from session start)")
    ap.add_argument("-o", "--output", type=Path, help="Write JSON (default: library/disp_catalog.json)")
    args = ap.parse_args()

    rows, t0 = load_frames(args.session)
    lo, hi = (args.window if args.window else (None, None))

    filtered = [r for r in rows if in_window(r, t0, lo, hi)]
    dur = (int(filtered[-1]["timestamp_ms"]) - int(filtered[0]["timestamp_ms"])) / 1000.0 if filtered else 0

    payload = {
        "session": args.session.name,
        "window_t_s": [lo, hi] if lo is not None else None,
        "duration_s": round(dur, 1),
        "disp_f0": {
            "ef00": catalog_pgn(filtered, "0xF0", "0xEF00", 3, DISP_EF00_KNOWN),
            "fff8": catalog_pgn(filtered, "0xF0", "0xFFF8", 3, DISP_FFF8_KNOWN),
            "fff4": catalog_pgn(filtered, "0xF0", "0xFFF4", 3, {}),
            "fef1": catalog_pgn(filtered, "0xF0", "0xFEF1", 2, {}),
        },
        "disp_26": {
            "e600": catalog_pgn(filtered, "0x26", "0xE600", 3, DISP_E600_KNOWN),
        },
        "pgn_summary": Counter(
            (r["sa_hex"], r["pgn_hex"]) for r in filtered if r["sa_hex"] in ("0xF0", "0x26")
        ).most_common(20),
    }

    if args.window:
        payload["mnc_cb00_window"] = mnc_window_diff(rows, t0, lo, hi)

    out = args.output or (LIB / ("disp_catalog_window.json" if args.window else "disp_catalog.json"))
    out.parent.mkdir(parents=True, exist_ok=True)
    # Convert Counter tuples for JSON
    payload["pgn_summary"] = [{"sa": a, "pgn": p, "frames": n} for (a, p), n in payload["pgn_summary"]]
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    print(f"{args.session.name}  DISP catalog  ->  {out}")
    ef = payload["disp_f0"]["ef00"]
    print(f"  0xF0 EF00: {ef['frame_count']} frames, {ef['unique_prefixes']} prefixes")
    for row in ef["catalog"][:5]:
        print(f"    {row['prefix']}  {row['pct']}%  {row['role']}  [{row['status']}]")
    e6 = payload["disp_26"]["e600"]
    print(f"  0x26 E600: {e6['frame_count']} frames, {e6['unique_prefixes']} VT chunks")
    if args.window:
        w = payload["mnc_cb00_window"]
        print(f"  MNC window {lo}-{hi}s: asc suffixes {w['asc_suffixes'][:5]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
