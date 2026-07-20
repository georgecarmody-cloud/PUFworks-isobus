"""Advanced record-filter dialog — library-backed checkboxes for IsobusWifiHub GUI."""

from __future__ import annotations

import sys
import tkinter as tk
from tkinter import ttk
from typing import Callable

SCRIPT_DIR = __import__("pathlib").Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from record_filter_lib import (  # noqa: E402
    CATEGORY_LABELS,
    STATUS_HINTS,
    default_record_filter_616r,
    default_record_filter_spray,
    filter_catalog,
    normalize_record_filter,
)


class RecordFilterDialog(tk.Toplevel):
    """Pick categories, nodes, and PGNs from spray_pgn_library + sniff_616r."""

    def __init__(
        self,
        parent: tk.Misc,
        record_filter: dict,
        on_save: Callable[[dict], None],
    ) -> None:
        super().__init__(parent)
        self.title("Advanced record filter")
        self.geometry("760x620")
        self.minsize(640, 480)
        self.transient(parent)
        self.grab_set()

        self._on_save = on_save
        self._cfg = normalize_record_filter(record_filter)
        self._catalog = filter_catalog()
        self._cat_vars: dict[str, tk.BooleanVar] = {}
        self._node_vars: dict[str, tk.BooleanVar] = {}
        self._pgn_vars: dict[str, tk.BooleanVar] = {}
        self._node_catchall = tk.BooleanVar(value=self._cfg.get("node_catchall", True))
        self._include_pf = tk.BooleanVar(value=self._cfg.get("include_pf_cb_a0", True))

        self._build()
        self._load_from_cfg()

    def _build(self) -> None:
        top = ttk.Frame(self, padding=10)
        top.pack(fill=tk.X)
        ttk.Label(
            top,
            text="Choose what is saved when a record session runs.\n"
            "Sources: spray_pgn_library.py + sniff_616r.py (see library/SPRAY_DECODE.md).",
            wraplength=700,
        ).pack(anchor="w")

        preset = ttk.Frame(self, padding=(10, 0))
        preset.pack(fill=tk.X)
        ttk.Button(preset, text="616r roster preset", command=self._preset_616r).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(preset, text="Spray library preset", command=self._preset_spray).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(preset, text="Select all", command=self._select_all).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(preset, text="Clear all", command=self._clear_all).pack(side=tk.LEFT)

        nb = ttk.Notebook(self, padding=8)
        nb.pack(fill=tk.BOTH, expand=True)
        nb.add(self._build_categories_tab(), text="Categories")
        nb.add(self._build_nodes_tab(), text="Nodes (SA)")
        nb.add(self._build_pgns_tab(), text="PGNs")

        opts = ttk.Frame(self, padding=10)
        opts.pack(fill=tk.X)
        ttk.Checkbutton(
            opts,
            text="Include all PGNs from selected nodes (616r catch-all)",
            variable=self._node_catchall,
        ).pack(anchor="w")
        ttk.Checkbutton(
            opts,
            text="Always include PF 0xCB (TC/sections) and PF 0xA0 (DDI rate)",
            variable=self._include_pf,
        ).pack(anchor="w")

        btns = ttk.Frame(self, padding=10)
        btns.pack(fill=tk.X)
        ttk.Button(btns, text="Save", command=self._save).pack(side=tk.RIGHT, padx=(6, 0))
        ttk.Button(btns, text="Cancel", command=self.destroy).pack(side=tk.RIGHT)

    def _scroll_frame(self, parent: ttk.Frame) -> tuple[tk.Canvas, ttk.Frame]:
        canvas = tk.Canvas(parent, highlightthickness=0)
        scroll = ttk.Scrollbar(parent, orient=tk.VERTICAL, command=canvas.yview)
        inner = ttk.Frame(canvas)
        inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=inner, anchor="nw")
        canvas.configure(yscrollcommand=scroll.set)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        return canvas, inner

    def _build_categories_tab(self) -> ttk.Frame:
        tab = ttk.Frame(self)
        _, inner = self._scroll_frame(tab)
        for cat in self._catalog["categories"]:
            cid = cat["id"]
            var = tk.BooleanVar()
            self._cat_vars[cid] = var
            row = ttk.Frame(inner)
            row.pack(fill=tk.X, pady=2)
            ttk.Checkbutton(row, text=cat["label"], variable=var).pack(side=tk.LEFT)
            ttk.Label(row, text=f"  ({cid})", foreground="#888").pack(side=tk.LEFT)
        return tab

    def _build_nodes_tab(self) -> ttk.Frame:
        tab = ttk.Frame(self)
        _, inner = self._scroll_frame(tab)
        for node in self._catalog["nodes"]:
            hx = node["sa_hex"]
            var = tk.BooleanVar()
            self._node_vars[hx] = var
            row = ttk.Frame(inner)
            row.pack(fill=tk.X, pady=1)
            ttk.Checkbutton(
                row,
                text=f"{node['label']}  {hx}  SA{node['sa']:03d}",
                variable=var,
            ).pack(side=tk.LEFT)
        return tab

    def _build_pgns_tab(self) -> ttk.Frame:
        tab = ttk.Frame(self)
        _, inner = self._scroll_frame(tab)
        for cat_id, entries in self._catalog["pgns_by_category"].items():
            if not entries:
                continue
            hdr = ttk.Label(
                inner,
                text=CATEGORY_LABELS.get(cat_id, cat_id),
                font=("Segoe UI", 9, "bold"),
            )
            hdr.pack(anchor="w", pady=(8, 2))
            for entry in entries:
                hx = entry["pgn_hex"]
                var = tk.BooleanVar()
                self._pgn_vars[hx] = var
                status = entry.get("status", "")
                hint = STATUS_HINTS.get(status, status)
                row = ttk.Frame(inner)
                row.pack(fill=tk.X, pady=1, padx=(8, 0))
                ttk.Checkbutton(
                    row,
                    text=f"{hx}  {entry['name']}",
                    variable=var,
                ).pack(side=tk.LEFT)
                ttk.Label(row, text=f"  [{status}] {hint}", foreground="#888").pack(side=tk.LEFT)
        return tab

    def _load_from_cfg(self) -> None:
        cats = set(self._cfg.get("categories") or [])
        nodes = set(self._cfg.get("nodes") or [])
        pgns = set(self._cfg.get("pgns") or [])
        for cid, var in self._cat_vars.items():
            var.set(cid in cats)
        for hx, var in self._node_vars.items():
            var.set(hx in nodes or hx.upper() in {n.upper() for n in nodes})
        for hx, var in self._pgn_vars.items():
            var.set(hx in pgns or hx.upper() in {p.upper() for p in pgns})

    def _preset_616r(self) -> None:
        self._apply_dict(default_record_filter_616r())

    def _preset_spray(self) -> None:
        self._apply_dict(default_record_filter_spray())

    def _apply_dict(self, d: dict) -> None:
        self._cfg = normalize_record_filter(d)
        self._node_catchall.set(self._cfg.get("node_catchall", True))
        self._include_pf.set(self._cfg.get("include_pf_cb_a0", True))
        self._load_from_cfg()

    def _select_all(self) -> None:
        for var in self._cat_vars.values():
            var.set(True)
        for var in self._node_vars.values():
            var.set(True)
        for var in self._pgn_vars.values():
            var.set(True)

    def _clear_all(self) -> None:
        for var in self._cat_vars.values():
            var.set(False)
        for var in self._node_vars.values():
            var.set(False)
        for var in self._pgn_vars.values():
            var.set(False)

    def _collect(self) -> dict:
        return normalize_record_filter(
            {
                "categories": [c for c, v in self._cat_vars.items() if v.get()],
                "nodes": [h for h, v in self._node_vars.items() if v.get()],
                "pgns": [h for h, v in self._pgn_vars.items() if v.get()],
                "node_catchall": self._node_catchall.get(),
                "include_pf_cb_a0": self._include_pf.get(),
            }
        )

    def _save(self) -> None:
        cfg = self._collect()
        self._on_save(cfg)
        self.destroy()
