#!/usr/bin/env python3
"""Build MNC CB00 map + SRC EF00 prefix catalog + SA roster from recorder sessions.

Usage:
  python scripts/decode_field_library.py
  python scripts/decode_field_library.py recordings/20260611_145535_616r_spray_asc
  python scripts/decode_field_library.py --live recordings/<new_session>

Writes:
  library/mnc_cb00_map.json
  library/src_ef00_catalog.json
  library/bus_roster.json
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sniff_616r import SA_LABELS_616R, sa_label, short_sa_label  # noqa: E402

LIB = ROOT / "library"
RECORDINGS = ROOT / "recordings"

# Known SRC EF00 prefixes (extend as confirmed)
SRC_EF00_KNOWN = {
    "4F0101": {"status": "confirmed", "role": "target_rate_l_ha", "decode": "u16[3:5]/10"},
    "F43401": {"status": "confirmed", "role": "rate_pressure_mode", "decode": "BE u16[3:5]/4.096 kPa"},
    "F43400": {"status": "confirmed", "role": "transport_mode_selector", "decode": "Transport counterpart to F43401; BE u16[3:5] static ~4096 (0x1000); dominant in 616r_transport — no kPa spray path"},
    "4F0B06": {"status": "confirmed", "role": "section_control", "decode": "bitmap + FF cmds"},
    "4F0601": {"status": "hypothesis", "role": "master_switch", "decode": "FF00 off / FF01 on"},
    "4F1401": {"status": "likely", "role": "flow_or_line_metric", "decode": "u16[3:5] churn ~1Hz during spray"},
    "4F3601": {"status": "likely", "role": "paired_flow_metric", "decode": "u16[3:5]+ trailing u16; pairs with 4F1401"},
    "4F1C01": {"status": "likely", "role": "aux_spray_metric", "decode": "u16[3:5] occasional burst"},
    "F10E4C": {"status": "likely", "role": "pressure_telemetry_rate_mode", "decode": "F10E family rate-mode; byte6-7 counter (~13% EF00 in rate sessions)"},
    "F10E1C": {"status": "confirmed", "role": "pressure_telemetry_transport_mode", "decode": "F10E family transport-mode; pairs with F43400; replaces F10E4C/5C off boom — 616r_transport 2026-06-15"},
    "F10E5C": {"status": "confirmed", "role": "pressure_telemetry_pressure_mode", "decode": "F10E family pressure-mode (1000 kPa); replaces F10E4C when F43401 kPa active — spray_live 2026-06-15"},
    "F009FF": {"status": "hypothesis", "role": "idle_marker", "decode": "F009FFFFFFFFFFFF sporadic"},
    "F00DFF": {"status": "hypothesis", "role": "idle_marker", "decode": "F00DFFFFFFFFFFFF static idle"},
    "F70400": {"status": "unknown", "role": "high_volume_idle", "decode": "F70400FFFFFFFFFF dominant idle family"},
    "F225FA": {"status": "hypothesis", "role": "session_marker", "decode": "F225FAFFFFFFFFFF bookend bursts"},
    "F22500": {"status": "likely", "role": "transport_idle_marker", "decode": "F22500FFFFFFFFFF; transport sessions alongside F43400/F10E1C"},
}

MNC_SUFFIX_KNOWN = {
    "110200": {"status": "likely", "role": "spray_active_idle_lane", "notes": "Dominant during application"},
    "110100": {"status": "likely", "role": "lane_handshake", "notes": "Secondary family; full_short sessions"},
    "100200": {"status": "likely", "role": "lane_alt_state", "notes": "F3100200 idle broadcast family"},
    "00A400": {"status": "likely", "role": "asc_turn_variant", "notes": "Headland / turn windows"},
    "00A500": {"status": "likely", "role": "asc_turn_variant", "notes": "Headland / turn windows"},
    "00A600": {"status": "likely", "role": "asc_turn_variant", "notes": "Headland / turn windows"},
    "00A100": {"status": "likely", "role": "transport_asc_variant", "notes": "616r_transport; lighter ASC family vs spray 00A4xx"},
    "00A200": {"status": "likely", "role": "transport_asc_variant", "notes": "616r_transport + spray slowdown windows"},
    "00A300": {"status": "likely", "role": "asc_turn_variant", "notes": "spray_live slowdown +195–215 s"},
}

# ASC cascade high-nibble lane keys (0x93=R5 hypothesis — field correlate)
MNC_LANE_BYTE0 = [
    ("0x03", "L5", "likely"),
    ("0x13", "L4", "likely"),
    ("0x23", "L3", "likely"),
    ("0x33", "L2", "likely"),
    ("0x43", "L1", "likely"),
    ("0x53", "C", "likely"),
    ("0x63", "R1", "likely"),
    ("0x73", "R2", "likely"),
    ("0x83", "R3", "likely"),
    ("0x93", "R4", "likely"),
    ("0xA3", "R5", "hypothesis"),
    ("0xF3", "summary_idle", "likely"),
    ("0xFF", "broadcast", "likely"),
]


def load_frames(sess: Path) -> list[dict]:
    path = sess / "frames.csv"
    if not path.exists():
        return []
    return list(csv.DictReader(open(path, newline="", encoding="utf-8")))


def session_ids(extra: list[Path] | None) -> list[Path]:
    if extra:
        return [p if p.is_dir() else p.parent for p in extra]
    if not RECORDINGS.exists():
        return []
    return sorted(p.parent for p in RECORDINGS.glob("*/frames.csv"))


def analyze_mnc_cb00(all_rows: list[tuple[str, dict]]) -> dict:
    """all_rows: (session_id, frame_row)"""
    by_prefix4 = Counter()
    by_prefix6 = Counter()
    by_lane_suffix = Counter()
    transitions: list[dict] = []
    prev_key: tuple[str, str] | None = None

    for sid, r in all_rows:
        if r["sa_hex"] != "0xD4" or r["pgn_hex"] != "0xCB00":
            continue
        hx = r["data_hex"].upper()
        if len(hx) < 8:
            continue
        p4 = hx[:8]
        p6 = hx[:12] if len(hx) >= 12 else p4
        lane = hx[:2]
        suffix = hx[2:8]
        by_prefix4[p4] += 1
        by_prefix6[p6] += 1
        by_lane_suffix[(lane, suffix)] += 1
        key = (lane, suffix)
        if prev_key and key != prev_key:
            transitions.append({
                "session": sid,
                "ts_ms": int(r["timestamp_ms"]),
                "from": f"{prev_key[0]}{prev_key[1]}",
                "to": f"{lane}{suffix}",
            })
        prev_key = key

    suffix_totals = Counter(s for _, s in by_lane_suffix.elements())
    lane_totals = Counter(l for l, _ in by_lane_suffix.elements())

    families = []
    for suffix, n in suffix_totals.most_common():
        meta = MNC_SUFFIX_KNOWN.get(suffix, {"status": "unknown", "role": "unclassified", "notes": ""})
        families.append({"suffix_hex": suffix, "frames": n, **meta})

    lanes = []
    lane_map = {k: name for k, name, _ in MNC_LANE_BYTE0}
    lane_status = {k: st for k, _, st in MNC_LANE_BYTE0}
    for b0, n in lane_totals.most_common():
        key = f"0x{b0}"
        lanes.append({
            "lane_byte0": key,
            "section_name": lane_map.get(key, "?"),
            "status": lane_status.get(key, "unknown"),
            "frames": n,
        })

    # ON-state suffix 110200 with high lane byte — spray active indicator
    on_prefixes = [p for p, n in by_prefix4.most_common() if p.endswith("110200") and p[:2] not in ("03", "F3")]

    return {
        "frame_count": sum(by_prefix4.values()),
        "unique_prefix4": len(by_prefix4),
        "unique_prefix6": len(by_prefix6),
        "top_prefix4": [{"prefix": p, "frames": n} for p, n in by_prefix4.most_common(30)],
        "suffix_families": families,
        "lane_byte0_map": [{"lane_byte0": k, "section_name": n, "status": s} for k, n, s in MNC_LANE_BYTE0],
        "lane_totals": lanes,
        "transition_count": len(transitions),
        "sample_transitions": transitions[:40],
        "grammar": {
            "prefix4": "byte0 lane key + bytes1-3 state suffix (6 hex chars)",
            "byte0": "0x03 + n*0x10 per boom lane (11 lanes + 0xF3 special + 0xFF bcast)",
            "suffix_110200": "dominant spray / lane-active family",
            "suffix_00A4xx": "ASC / turn / headland variant family",
            "asc_on_cascade": "93110200 -> 83110200 -> ... descending byte0 during section re-entry",
        },
    }


def analyze_jd_sec_cb00(all_rows: list[tuple[str, dict]]) -> dict:
    by_prefix4 = Counter()
    for _, r in all_rows:
        if r["sa_hex"] != "0xF7" or r["pgn_hex"] != "0xCB00":
            continue
        hx = r["data_hex"].upper()
        if len(hx) >= 8:
            by_prefix4[hx[:8]] += 1
    return {
        "frame_count": sum(by_prefix4.values()),
        "unique_prefix4": len(by_prefix4),
        "top_prefix4": [{"prefix": p, "frames": n} for p, n in by_prefix4.most_common(20)],
        "notes": "Compare prefix families to MNC 0xD4 — often mirrored or offset timing",
    }


def ef00_prefix(hx: str) -> str:
    """First 3 bytes (6 hex chars) = JD element id for 4Fxx01 / F4xx01 families."""
    hx = hx.upper()
    if len(hx) >= 6:
        return hx[:6]
    return hx


def analyze_src_ef00(all_rows: list[tuple[str, dict]]) -> dict:
    by_prefix = Counter()
    by_prefix_session = defaultdict(Counter)
    samples: dict[str, str] = {}

    for sid, r in all_rows:
        if r["sa_hex"] != "0xE1" or r["pgn_hex"] != "0xEF00":
            continue
        hx = r["data_hex"].upper()
        if len(hx) < 8:
            continue
        p4 = ef00_prefix(hx)
        by_prefix[p4] += 1
        by_prefix_session[p4][sid] += 1
        if p4 not in samples:
            samples[p4] = hx

    total = sum(by_prefix.values())
    catalog = []
    for p4, n in by_prefix.most_common():
        known = SRC_EF00_KNOWN.get(p4, {})
        pct = round(100.0 * n / total, 2) if total else 0
        catalog.append({
            "prefix": p4,
            "frames": n,
            "pct_of_src_ef00": pct,
            "sample": samples.get(p4, ""),
            "status": known.get("status", "unknown"),
            "role": known.get("role", "unclassified"),
            "decode": known.get("decode", ""),
            "sessions_seen": len(by_prefix_session[p4]),
        })

    return {
        "frame_count": total,
        "unique_prefix4": len(by_prefix),
        "catalog": catalog,
        "coverage_known_pct": round(
            100.0 * sum(c["frames"] for c in catalog if c["status"] in ("confirmed", "likely")) / max(total, 1),
            1,
        ),
    }


def analyze_mnc_ef00(all_rows: list[tuple[str, dict]]) -> dict:
    by_prefix = Counter()
    samples: dict[str, str] = {}
    for sid, r in all_rows:
        if r["sa_hex"] != "0xD4" or r["pgn_hex"] != "0xEF00":
            continue
        hx = r["data_hex"].upper()
        p4 = ef00_prefix(hx)
        by_prefix[p4] += 1
        if p4 not in samples:
            samples[p4] = hx
    return {
        "frame_count": sum(by_prefix.values()),
        "top_prefix6": [
            {"prefix": p, "frames": n, "sample": samples.get(p, "")}
            for p, n in by_prefix.most_common(25)
        ],
    }


def analyze_roster(all_rows: list[tuple[str, dict]]) -> dict:
    by_sa = Counter()
    by_pair = Counter()
    unknown_sas: set[int] = set()

    for _, r in all_rows:
        sa_h = r.get("sa_hex", "")
        pgn_h = r.get("pgn_hex", "")
        if not sa_h.startswith("0x"):
            continue
        sa = int(sa_h, 16)
        by_sa[sa_h] += 1
        by_pair[(sa_h, pgn_h)] += 1
        if sa not in SA_LABELS_616R:
            unknown_sas.add(sa)

    nodes = []
    for sa_h, n in by_sa.most_common():
        sa = int(sa_h, 16)
        top_pgns = [
            {"pgn": p, "frames": c}
            for (s, p), c in by_pair.most_common()
            if s == sa_h
        ][:8]
        nodes.append({
            "sa_hex": sa_h,
            "sa_dec": sa,
            "label": short_sa_label(sa),
            "full_label": sa_label(sa),
            "in_roster": sa in SA_LABELS_616R,
            "frames": n,
            "top_pgns": top_pgns,
        })

    return {
        "node_count": len(nodes),
        "unknown_sas": [
            {"sa_hex": f"0x{sa:02X}", "sa_dec": sa, "frames": by_sa[f"0x{sa:02X}"]}
            for sa in sorted(unknown_sas)
        ],
        "nodes": nodes,
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("sessions", nargs="*", type=Path, help="Session dirs (default: all recordings)")
    ap.add_argument("--live", type=Path, help="Highlight this session in report header")
    args = ap.parse_args()

    sess_paths = session_ids(args.sessions if args.sessions else None)
    if not sess_paths:
        print("No sessions found.", file=sys.stderr)
        return 1

    all_rows: list[tuple[str, dict]] = []
    session_meta = []
    for sp in sess_paths:
        frames = load_frames(sp)
        if not frames:
            continue
        session_meta.append({"id": sp.name, "frames": len(frames)})
        for r in frames:
            all_rows.append((sp.name, r))

    print(f"Loaded {len(all_rows)} frames from {len(session_meta)} sessions")

    mnc = analyze_mnc_cb00(all_rows)
    jd_sec = analyze_jd_sec_cb00(all_rows)
    src_ef = analyze_src_ef00(all_rows)
    mnc_ef = analyze_mnc_ef00(all_rows)
    roster = analyze_roster(all_rows)

    payload = {
        "compiled_at": datetime.now(timezone.utc).isoformat(),
        "live_session": args.live.name if args.live else None,
        "sessions": session_meta,
        "mnc_cb00": mnc,
        "jd_sec_cb00": jd_sec,
        "src_ef00": src_ef,
        "mnc_ef00": mnc_ef,
        "roster": roster,
    }

    LIB.mkdir(parents=True, exist_ok=True)
    (LIB / "mnc_cb00_map.json").write_text(json.dumps(mnc, indent=2), encoding="utf-8")
    (LIB / "src_ef00_catalog.json").write_text(json.dumps(src_ef, indent=2), encoding="utf-8")
    (LIB / "bus_roster.json").write_text(json.dumps(roster, indent=2), encoding="utf-8")
    (LIB / "field_library_snapshot.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")

    print(f"\nMNC CB00: {mnc['frame_count']} frames, {mnc['unique_prefix4']} prefix4")
    print("  Top suffix families:", [f["suffix_hex"] for f in mnc["suffix_families"][:5]])
    print(f"SRC EF00: {src_ef['frame_count']} frames, {src_ef['unique_prefix4']} prefixes, known coverage {src_ef['coverage_known_pct']}%")
    print("  Top unknown prefixes:")
    for row in src_ef["catalog"][:12]:
        if row["status"] == "unknown":
            print(f"    {row['prefix']}  {row['pct_of_src_ef00']}%  {row['sample'][:24]}...")
    if roster["unknown_sas"]:
        print("Unknown SAs:", roster["unknown_sas"])
    print(f"\nWrote library/mnc_cb00_map.json, src_ef00_catalog.json, bus_roster.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
