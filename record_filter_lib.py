"""
Record-session filter catalog — sourced from spray_pgn_library + sniff_616r.

Used by bus_engine (SET_RECORD_FILTER / sniff_mode=custom) and IsobusWifiHub GUI.
"""

from __future__ import annotations

from typing import Any

from sniff_616r import EXTRA_WATCH_PGNS_616R, SA_LABELS_616R, WATCH_SAS_616R
from spray_pgn_library import PGN_CATALOG, SPRAY_CATEGORIES, SPRAY_WATCH_SAS, pgn_info

CATEGORY_LABELS: dict[str, str] = {
    "gps_motion": "GPS / motion",
    "rate_section": "Rate / sections / TC",
    "flow_pressure": "Flow / pressure",
    "boom_height": "Boom height",
    "spray_proprietary": "Spray proprietary / OEM",
}

STATUS_HINTS: dict[str, str] = {
    "confirmed": "Field confirmed",
    "likely": "Likely on wire",
    "hypothesis": "Hypothesis — capture to confirm",
    "parked": "Parked — decode disproven or unused",
    "not_on_ib1": "Not on X119 implement tap",
    "unknown": "Unknown — add to catalog after decode",
}


def _unique_nodes() -> list[dict]:
    """616R roster nodes for UI (one row per SA)."""
    rows = []
    for sa in sorted(WATCH_SAS_616R):
        rows.append(
            {
                "sa": sa,
                "sa_hex": f"0x{sa:02X}",
                "label": SA_LABELS_616R.get(sa, f"SA{sa:03d}"),
                "notes": "616R implement bus roster (sniff_616r.WATCH_SAS_616R)",
            }
        )
    return rows


def filter_catalog() -> dict[str, Any]:
    """Full catalog for Advanced record-filter UI."""
    pgns_by_cat: dict[str, list[dict]] = {c: [] for c in SPRAY_CATEGORIES}
    for entry in PGN_CATALOG:
        cat = entry.get("category", "spray_proprietary")
        if cat not in pgns_by_cat:
            pgns_by_cat[cat] = []
        pgns_by_cat[cat].append(
            {
                "pgn": entry["pgn"],
                "pgn_hex": f"0x{entry['pgn']:04X}",
                "name": entry.get("name", ""),
                "status": entry.get("status", "unknown"),
                "status_hint": STATUS_HINTS.get(entry.get("status", ""), ""),
                "notes": entry.get("notes", ""),
            }
        )
    return {
        "source": "spray_pgn_library.PGN_CATALOG + sniff_616r.WATCH_SAS_616R",
        "categories": [
            {
                "id": cat,
                "label": CATEGORY_LABELS.get(cat, cat),
                "description": STATUS_HINTS.get("confirmed", ""),
            }
            for cat in SPRAY_CATEGORIES
        ],
        "nodes": _unique_nodes(),
        "pgns_by_category": pgns_by_cat,
    }


def default_record_filter_616r() -> dict:
    return {
        "categories": list(SPRAY_CATEGORIES),
        "nodes": [f"0x{sa:02X}" for sa in sorted(WATCH_SAS_616R)],
        "pgns": [f"0x{p:04X}" for p in sorted(EXTRA_WATCH_PGNS_616R)],
        "node_catchall": True,
        "include_pf_cb_a0": True,
    }


def default_record_filter_spray() -> dict:
    pgns = sorted({e["pgn"] for e in PGN_CATALOG})
    return {
        "categories": list(SPRAY_CATEGORIES),
        "nodes": [f"0x{sa:02X}" for sa in sorted(SPRAY_WATCH_SAS)],
        "pgns": [f"0x{p:04X}" for p in pgns],
        "node_catchall": True,
        "include_pf_cb_a0": True,
    }


def preset_record_filter(sniff_mode: str) -> dict | None:
    if sniff_mode == "616r":
        return default_record_filter_616r()
    if sniff_mode == "spray":
        return default_record_filter_spray()
    return None


def normalize_record_filter(raw: dict | None) -> dict:
    if not raw:
        return default_record_filter_616r()
    out = {
        "categories": list(raw.get("categories") or []),
        "nodes": list(raw.get("nodes") or []),
        "pgns": list(raw.get("pgns") or []),
        "node_catchall": bool(raw.get("node_catchall", True)),
        "include_pf_cb_a0": bool(raw.get("include_pf_cb_a0", True)),
    }
    return out


def _parse_hex_set(items: list, width: int = 2) -> set[int]:
    out: set[int] = set()
    for item in items:
        s = str(item).strip()
        if not s:
            continue
        out.add(int(s, 16) if s.lower().startswith("0x") else int(s))
    return out


def frame_matches_custom_filter(pf: int, sa: int, pgn: int, filt: dict) -> bool:
    """True if frame should be written to record session (custom mode)."""
    cfg = normalize_record_filter(filt)
    cats = set(cfg["categories"])
    nodes = _parse_hex_set(cfg["nodes"])
    pgns = _parse_hex_set(cfg["pgns"], width=4)
    node_catchall = cfg["node_catchall"]
    include_pf = cfg["include_pf_cb_a0"]

    if include_pf and pf in (0xA0, 0xCB):
        return True
    if pgn in pgns:
        return True
    info = pgn_info(pgn, pf)
    if info.get("category") in cats and pgn in {e["pgn"] for e in PGN_CATALOG}:
        return True
    if sa in nodes:
        if node_catchall:
            return True
        if pgn in pgns or info.get("category") in cats:
            return True
    return False
