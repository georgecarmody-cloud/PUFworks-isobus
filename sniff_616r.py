"""
616R See & Spray CAN sniff helpers — SA labels, roster, and post-session analysis.

Authoritative roster: JD_ISOBUS_MAP.md §3.2, §12.3–§12.4.
DTCs reference decimal SAs; field logs include both hex and decimal.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Dict, Iterable, Optional, Set

# Implement bus (IB1 / X119) nodes — never claim these SAs.
WATCH_SAS_616R: Set[int] = {
    0x00,  # Engine ECU
    0x06,  # TC server (common)
    0x17, 0xE1,  # SRC / PSSC spray rate
    0x1C,  # ATX AutoTrac
    0x26, 0xF0,  # Gen 4/5 display / terminal
    0x68, 0xD4, 0x69, 0xCD,  # MNC / NZC family
    0x8A,  # BHC boom height
    0x94,  # GWC gateway (See & Spray hub)
    0xA2,  # VPU family (DTC SA 162)
    0xCC,  # GRC if present on implement bus
    0xF7,  # JD section-control source (0xCB00)
    0xBA, 0xB9, 0xD5,  # E700/EF00 peers — label after Diagnostics
}

SA_LABELS_616R: Dict[int, str] = {
    0x00: "ENG",
    0x06: "TC",
    0x17: "SRC",
    0xE1: "SRC",
    0x1C: "ATX",
    0x26: "DISP",
    0xF0: "DISP",
    0x68: "MNC",
    0xD4: "MNC",
    0x69: "MNC",
    0xCD: "NZC",
    0x8A: "BHC",
    0x94: "GWC",
    0xA2: "VPU",
    0xCC: "GRC",
    0xF7: "JD_SEC",
    0xBA: "AUX_E700",
    0xB9: "AUX_E700",
    0xD5: "AUX_EF00",
}

# PGNs worth retaining beyond the Goldacres-centric default filter.
EXTRA_WATCH_PGNS_616R: Set[int] = {
    0xCB00, 0xEA00, 0xEE00, 0xFE0D, 0xFEF1, 0xFEE8, 0xFEE6, 0xFEF3,
    0xFECA, 0xE700, 0xEF00, 65267, 59136,
    0x00A0,  # PGN 160 process data (DDI 157/158)
    0x00E6,  # VT transport
    0x00FE,  # multipacket / transport family
}

SNIFF_MODES = ("filtered", "spray", "616r", "616r_full")


def sa_label(sa: int) -> str:
    """Human label for a source address (hex + decimal DTC style)."""
    name = SA_LABELS_616R.get(sa)
    if name:
        return f"{name}/0x{sa:02X}/SA{sa:03d}"
    return f"0x{sa:02X}/SA{sa:03d}"


def short_sa_label(sa: int) -> str:
    return SA_LABELS_616R.get(sa, f"SA{sa:03d}")


def parse_sa_hex(text: str) -> int:
    text = text.strip()
    if text.lower().startswith("0x"):
        return int(text, 16)
    return int(text)


def summarize_frames(rows: Iterable[dict]) -> dict:
    """Build a 616R-oriented summary from frames.csv DictReader rows."""
    rows = list(rows)
    if not rows:
        return {"frame_count": 0}

    by_sa = Counter(r.get("sa_hex", "") for r in rows)
    by_pgn = Counter(r.get("pgn_hex", "") for r in rows)
    by_sa_pgn = Counter((r.get("sa_hex", ""), r.get("pgn_hex", "")) for r in rows)

    key_nodes = {}
    for sa in (0x94, 0x17, 0xE1, 0x68, 0x8A, 0x1C, 0x26, 0xF7, 0xCC):
        hx = f"0x{sa:02X}"
        key_nodes[short_sa_label(sa)] = by_sa.get(hx, 0)

    ef00 = [r for r in rows if r.get("pgn_hex") == "0xEF00"]
    ef00_by_sa = Counter(r.get("sa_hex", "") for r in ef00)

    cb00 = [r for r in rows if r.get("pgn_hex") == "0xCB00"]
    fef1 = [r for r in rows if r.get("pgn_hex") == "0xFEF1"]

    speed_samples = []
    for r in fef1:
        try:
            b = bytes.fromhex(r["data_hex"])
            if len(b) >= 3:
                raw = b[1] | (b[2] << 8)
                if raw != 0xFFFF:
                    speed_samples.append(raw / 256.0)
        except (ValueError, KeyError):
            pass

    return {
        "frame_count": len(rows),
        "unique_sas": len(by_sa),
        "top_sas": by_sa.most_common(12),
        "top_pgns": by_pgn.most_common(12),
        "key_node_frames": key_nodes,
        "ef00_frames": len(ef00),
        "ef00_by_sa": ef00_by_sa.most_common(8),
        "cb00_frames": len(cb00),
        "fef1_frames": len(fef1),
        "speed_kmh_min": round(min(speed_samples), 2) if speed_samples else None,
        "speed_kmh_max": round(max(speed_samples), 2) if speed_samples else None,
        "speed_kmh_median": round(sorted(speed_samples)[len(speed_samples) // 2], 2) if speed_samples else None,
        "top_sa_pgn": by_sa_pgn.most_common(16),
    }


def print_616r_report(sess_name: str, meta: dict, frame_summary: dict, shadow_rows: Optional[list] = None):
    print("=" * 72)
    print(f"616R SNIFF REPORT — {sess_name}")
    print("=" * 72)
    print(f"Profile: {meta.get('sprayer_profile')}  Sniff: {meta.get('sniff_mode', 'filtered')}")
    print(f"Duration: {meta.get('duration_s', '?')}s  Frames: {meta.get('frame_count', frame_summary.get('frame_count'))}")
    if meta.get("label"):
        print(f"Label: {meta['label']}")
    if meta.get("node_rx_counts"):
        print("\nNode RX counts (record filter):")
        for sa, n in sorted(meta["node_rx_counts"].items(), key=lambda x: -x[1])[:20]:
            try:
                sa_int = int(sa, 16)
                print(f"  {sa_label(sa_int):28s}  {n:6d}")
            except ValueError:
                print(f"  {sa:28s}  {n:6d}")

    print(f"\nUnique SAs on wire: {frame_summary.get('unique_sas', 0)}")
    print("Key implement nodes:")
    for name, n in (frame_summary.get("key_node_frames") or {}).items():
        mark = "✓" if n else "—"
        print(f"  [{mark}] {name:8s}  {n:6d} frames")

    print("\nTop source addresses:")
    for hx, n in frame_summary.get("top_sas", [])[:10]:
        try:
            print(f"  {sa_label(parse_sa_hex(hx)):28s}  {n:6d}")
        except ValueError:
            print(f"  {hx:28s}  {n:6d}")

    print("\nTop PGNs:")
    for pgn, n in frame_summary.get("top_pgns", [])[:10]:
        print(f"  {pgn:8s}  {n:6d}")

    if frame_summary.get("fef1_frames"):
        print(
            f"\nSpeed (FEF1): {frame_summary.get('speed_kmh_min')}–"
            f"{frame_summary.get('speed_kmh_max')} km/h "
            f"(median {frame_summary.get('speed_kmh_median')})"
        )

    if frame_summary.get("ef00_frames"):
        print(f"\nEF00 proprietary ({frame_summary['ef00_frames']} frames) by SA:")
        for hx, n in frame_summary.get("ef00_by_sa", []):
            try:
                print(f"  {sa_label(parse_sa_hex(hx)):28s}  {n:6d}")
            except ValueError:
                print(f"  {hx:28s}  {n:6d}")
        print("  (Goldacres GRC decode targets SA 0xCC; 616R may use other SAs — inspect payloads.)")

    if frame_summary.get("cb00_frames"):
        print(f"\nCB00 section/TC traffic: {frame_summary['cb00_frames']} frames")

    print("\nTop (SA, PGN) pairs:")
    for (sa, pgn), n in frame_summary.get("top_sa_pgn", [])[:12]:
        try:
            print(f"  {short_sa_label(parse_sa_hex(sa)):6s} {pgn:8s}  {n:6d}")
        except ValueError:
            print(f"  {sa:6s} {pgn:8s}  {n:6d}")

    if shadow_rows:
        hosts = Counter(r.get("host_commanded_bitmap", "") for r in shadow_rows)
        print(f"\nShadow rows: {len(shadow_rows)}  host_bitmap samples: {hosts.most_common(3)}")
        if shadow_rows and "gwc_alive" in shadow_rows[0]:
            alive = {
                "GWC": sum(1 for r in shadow_rows if r.get("gwc_alive") == "1"),
                "SRC": sum(1 for r in shadow_rows if r.get("src_alive") == "1"),
                "MNC": sum(1 for r in shadow_rows if r.get("mnc_alive") == "1"),
            }
            print(f"  Node alive fraction: {', '.join(f'{k}={v}/{len(shadow_rows)}' for k, v in alive.items())}")

    print()
