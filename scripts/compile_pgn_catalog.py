#!/usr/bin/env python3
"""
Merge field recorder sessions into the spray PGN observation library.

Scans recordings/*/frames.csv, tallies (SA, PGN) pairs, flags unknown high-traffic
PGNs for catalog extension, and writes library/field_observations.json.

Usage:
  python scripts/compile_pgn_catalog.py
  python scripts/compile_pgn_catalog.py recordings/20260611_616r_drive
"""
import csv
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sniff_616r import sa_label, short_sa_label
from spray_pgn_library import PGN_CATALOG, SPRAY_PGNS, export_library_json, pgn_info

ROOT = Path(__file__).resolve().parents[1]
RECORDINGS = ROOT / "recordings"
OUT = ROOT / "library" / "field_observations.json"


def scan_session(sess: Path) -> dict:
    frames_path = sess / "frames.csv"
    if not frames_path.exists():
        return {}
    rows = list(csv.DictReader(open(frames_path, newline="", encoding="utf-8")))
    if not rows:
        return {"session": sess.name, "frame_count": 0}

    by_pgn = Counter(r.get("pgn_hex", "") for r in rows)
    by_sa = Counter(r.get("sa_hex", "") for r in rows)
    by_pair = Counter((r.get("sa_hex", ""), r.get("pgn_hex", "")) for r in rows)
    by_cat = Counter(r.get("category", "unknown") for r in rows if r.get("category"))

    unknown_pgns = []
    for pgn_hex, n in by_pgn.most_common():
        if not pgn_hex:
            continue
        try:
            pgn = int(pgn_hex, 16)
        except ValueError:
            continue
        if pgn not in SPRAY_PGNS:
            unknown_pgns.append({"pgn_hex": pgn_hex, "pgn_dec": pgn, "frames": n,
                                 "suggested": pgn_info(pgn)})

    return {
        "session": sess.name,
        "frame_count": len(rows),
        "meta": json.loads((sess / "session_meta.json").read_text(encoding="utf-8"))
        if (sess / "session_meta.json").exists() else {},
        "top_pgns": by_pgn.most_common(20),
        "top_sas": by_sa.most_common(15),
        "top_pairs": [
            {"sa": sa, "pgn": pgn, "n": n,
             "sa_label": sa_label(int(sa, 16)) if sa.startswith("0x") else sa}
            for (sa, pgn), n in by_pair.most_common(25)
        ],
        "categories": dict(by_cat),
        "unknown_pgns": unknown_pgns[:15],
    }


def main():
    targets = [Path(p) for p in sys.argv[1:]] if len(sys.argv) > 1 else None
    if targets:
        sessions = [t for t in targets if (t / "frames.csv").exists()]
    else:
        sessions = sorted(RECORDINGS.glob("*/frames.csv"))
        sessions = [p.parent for p in sessions]

    if not sessions:
        print("No recorder sessions found.")
        sys.exit(1)

    reports = [scan_session(s) for s in sessions]
    reports = [r for r in reports if r]

    aggregate_pairs = Counter()
    aggregate_pgns = Counter()
    for r in reports:
        for item in r.get("top_pairs", []):
            aggregate_pairs[(item["sa"], item["pgn"])] += item["n"]
        for pgn_hex, n in r.get("top_pgns", []):
            aggregate_pgns[pgn_hex] += n

    payload = {
        "compiled_at": __import__("datetime").datetime.now().isoformat(),
        "catalog_entries": len(PGN_CATALOG),
        "sessions_scanned": len(reports),
        "aggregate_top_pairs": [
            {"sa": sa, "pgn": pgn, "frames": n,
             "sa_label": sa_label(int(sa, 16)) if sa.startswith("0x") else sa,
             "pgn_info": pgn_info(int(pgn, 16)) if pgn.startswith("0x") else {}}
            for (sa, pgn), n in aggregate_pairs.most_common(40)
        ],
        "aggregate_top_pgns": aggregate_pgns.most_common(25),
        "sessions": reports,
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    export_library_json()

    print(f"Scanned {len(reports)} session(s) -> {OUT}")
    print(f"Catalog: {len(PGN_CATALOG)} entries in library/spray_pgn_library.json")
    print("\nAggregate top (SA, PGN):")
    for item in payload["aggregate_top_pairs"][:12]:
        print(f"  {item['sa_label']:28s}  {item['pgn']:8s}  {item['frames']:6d}")


if __name__ == "__main__":
    main()
