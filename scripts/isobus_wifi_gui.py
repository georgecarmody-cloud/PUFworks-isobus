#!/usr/bin/env python3
"""Native Windows GUI for PUFworks ISOBUS WiFi Hub.

Visual language from PUFworks.farm (concrete / hazard / phosphor).
Licensed Fox Rockett Studio vector motifs used as UI chrome only — not co-branding.
"""

from __future__ import annotations

import sys
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

SCRIPT_DIR = __import__("pathlib").Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from isobus_hub_service import HubService  # noqa: E402
from isobus_record_filter_ui import RecordFilterDialog  # noqa: E402
from isobus_wifi_hub import (  # noqa: E402
    config_path,
    default_recordings_dir,
    load_config,
    run_engine_child,
    save_config,
)
from isobus_wifi_web import lan_ip, list_com_ports  # noqa: E402
from record_filter_lib import (  # noqa: E402
    default_record_filter_616r,
    normalize_record_filter,
    preset_record_filter,
)

# PUFworks.farm tokens (tk-friendly)
C_SLAB = "#141210"
C_CONCRETE = "#1c1a16"
C_CONCRETE_MID = "#2a2620"
C_CONCRETE_LIT = "#3d3830"
C_EDGE = "#3a342c"
C_TEXT = "#e6e0d4"
C_TEXT_DIM = "#a89e8c"
C_MUTED = "#6e6658"
C_PHOSPHOR = "#8fd99a"
C_PHOSPHOR_DIM = "#4a8a52"
C_SODIUM = "#d4893a"
C_HAZARD = "#c9a227"
C_DANGER = "#9a2e2e"
C_DANGER_LIT = "#c44a4a"
C_LOG_BG = "#0a0908"

FIX_LABELS = {0: "Invalid", 1: "GPS", 2: "DGPS", 4: "RTK fixed", 5: "RTK float"}
NODE_KEYS = [
    ("gwc_alive", "GWC"),
    ("src_alive", "SRC"),
    ("mnc_alive", "MNC"),
    ("bhc_alive", "BHC"),
    ("atx_alive", "ATX"),
    ("grc_alive", "GRC"),
]
RECORD_PRESETS = [
    ("616r", "616R implement roster"),
    ("spray", "Spray PGN library"),
    ("filtered", "Minimal / filtered"),
    ("616r_full", "Full bus (record only)"),
    ("custom", "Custom (Advanced…)"),
]
REFRESH_MS = 500


class HubApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("PUFworks · ISOBUS WiFi Hub")
        self.minsize(760, 640)
        self.geometry("880x720")
        self.configure(bg=C_SLAB)

        self._cfg = load_config()
        if "record_filter" not in self._cfg:
            self._cfg["record_filter"] = default_record_filter_616r()
        self._record_filter = normalize_record_filter(self._cfg.get("record_filter"))
        self._service = HubService(self._cfg, enable_web=False, on_log=self._append_log)
        self._vars: dict[str, tk.Variable] = {}
        self._node_labels: dict[str, tk.Label] = {}
        self._running = False
        self._recording = False

        self._build_style()
        self._build_ui()
        self._load_form()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(REFRESH_MS, self._tick)

    def _build_style(self) -> None:
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("TFrame", background=C_CONCRETE)
        style.configure("Slab.TFrame", background=C_SLAB)
        style.configure("Mid.TFrame", background=C_CONCRETE_MID)
        style.configure("TLabel", background=C_CONCRETE, foreground=C_TEXT, font=("Segoe UI", 9))
        style.configure("Slab.TLabel", background=C_SLAB, foreground=C_TEXT)
        style.configure(
            "Brand.TLabel",
            background=C_SLAB,
            foreground=C_HAZARD,
            font=("Segoe UI", 9, "bold"),
        )
        style.configure(
            "Title.TLabel",
            background=C_SLAB,
            foreground=C_TEXT,
            font=("Segoe UI", 16, "bold"),
        )
        style.configure(
            "Sub.TLabel",
            background=C_SLAB,
            foreground=C_TEXT_DIM,
            font=("Segoe UI", 9),
        )
        style.configure(
            "StatusRun.TLabel",
            background=C_SLAB,
            foreground=C_PHOSPHOR,
            font=("Segoe UI", 11, "bold"),
        )
        style.configure(
            "StatusStop.TLabel",
            background=C_SLAB,
            foreground=C_SODIUM,
            font=("Segoe UI", 11, "bold"),
        )
        style.configure("Hint.TLabel", background=C_CONCRETE, foreground=C_MUTED, font=("Segoe UI", 8))
        style.configure(
            "GPS.TLabel",
            background=C_CONCRETE,
            foreground=C_PHOSPHOR,
            font=("Consolas", 12, "bold"),
        )
        style.configure(
            "Metric.TLabel",
            background=C_CONCRETE,
            foreground=C_TEXT,
            font=("Consolas", 10),
        )
        style.configure(
            "TLabelframe",
            background=C_CONCRETE,
            foreground=C_TEXT_DIM,
            bordercolor=C_EDGE,
            relief="solid",
        )
        style.configure(
            "TLabelframe.Label",
            background=C_CONCRETE,
            foreground=C_HAZARD,
            font=("Segoe UI", 9, "bold"),
        )
        style.configure(
            "TButton",
            background=C_CONCRETE_LIT,
            foreground=C_TEXT,
            bordercolor=C_EDGE,
            focuscolor=C_EDGE,
            padding=(10, 6),
            font=("Segoe UI", 9),
        )
        style.map(
            "TButton",
            background=[("active", C_EDGE), ("disabled", C_CONCRETE_MID)],
            foreground=[("disabled", C_MUTED)],
        )
        style.configure(
            "TCombobox",
            fieldbackground=C_CONCRETE_MID,
            background=C_CONCRETE_MID,
            foreground=C_TEXT,
            arrowcolor=C_HAZARD,
        )
        style.configure(
            "TEntry",
            fieldbackground=C_CONCRETE_MID,
            foreground=C_TEXT,
            insertcolor=C_TEXT,
        )
        style.configure(
            "TCheckbutton",
            background=C_CONCRETE,
            foreground=C_TEXT,
            font=("Segoe UI", 9),
        )
        style.map("TCheckbutton", background=[("active", C_CONCRETE)])

    def _var(self, key: str, default="") -> tk.StringVar:
        if key not in self._vars:
            self._vars[key] = tk.StringVar(value=str(default))
        return self._vars[key]

    def _hazard_stripe(self, parent: tk.Widget, height: int = 8) -> None:
        stripe = tk.Canvas(parent, height=height, bg=C_SLAB, highlightthickness=0, bd=0)
        stripe.pack(fill=tk.X)
        # Aliens-style diagonal hazard tape
        w = 920
        for i in range(-height, w, 16):
            stripe.create_polygon(
                i,
                0,
                i + 8,
                0,
                i + 8 + height,
                height,
                i + height,
                height,
                fill=C_HAZARD,
                outline="",
            )
        stripe.configure(scrollregion=(0, 0, w, height))

        def _resize(event: tk.Event) -> None:
            stripe.delete("all")
            width = max(event.width, 16)
            for i in range(-height, width + 16, 16):
                stripe.create_polygon(
                    i,
                    0,
                    i + 8,
                    0,
                    i + 8 + height,
                    height,
                    i + height,
                    height,
                    fill=C_HAZARD,
                    outline="",
                )

        stripe.bind("<Configure>", _resize)

    def _build_ui(self) -> None:
        self._hazard_stripe(self, 10)

        outer = ttk.Frame(self, style="Slab.TFrame", padding=(16, 12, 16, 14))
        outer.pack(fill=tk.BOTH, expand=True)

        self._build_header(outer)
        self._build_start_bar(outer)

        body = ttk.Frame(outer, style="Slab.TFrame")
        body.pack(fill=tk.BOTH, expand=True, pady=(14, 0))
        body.columnconfigure(0, weight=1)
        body.columnconfigure(1, weight=1)

        self._build_gps_panel(body)
        self._build_can_panel(body)
        self._build_net_panel(body)
        self._build_sniff_panel(body)
        self._build_live_panel(body)
        self._build_log_panel(outer)
        self._build_footer(outer)

    def _build_header(self, parent: ttk.Frame) -> None:
        header = ttk.Frame(parent, style="Slab.TFrame")
        header.pack(fill=tk.X)

        left = ttk.Frame(header, style="Slab.TFrame")
        left.pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Label(left, text="PUFWORKS", style="Brand.TLabel").pack(anchor="w")
        ttk.Label(left, text="ISOBUS WiFi Hub", style="Title.TLabel").pack(anchor="w", pady=(2, 0))
        ttk.Label(
            left,
            text="CANable → decode → Wi‑Fi  ·  tablet GPS on UDP 9999  ·  OBSERVE only",
            style="Sub.TLabel",
        ).pack(anchor="w", pady=(2, 0))

        right = ttk.Frame(header, style="Slab.TFrame")
        right.pack(side=tk.RIGHT, padx=(12, 0))
        self._status_dot = tk.Label(
            right, text="●", bg=C_SLAB, fg=C_SODIUM, font=("Segoe UI", 18)
        )
        self._status_dot.pack(side=tk.LEFT, padx=(0, 6))
        self._status_var = tk.StringVar(value="STOPPED")
        self._status_lbl = ttk.Label(
            right, textvariable=self._status_var, style="StatusStop.TLabel"
        )
        self._status_lbl.pack(side=tk.LEFT)

    def _build_start_bar(self, parent: ttk.Frame) -> None:
        bar = tk.Frame(parent, bg=C_CONCRETE_MID, highlightbackground=C_EDGE, highlightthickness=1)
        bar.pack(fill=tk.X, pady=(14, 0))

        inner = tk.Frame(bar, bg=C_CONCRETE_MID)
        inner.pack(fill=tk.X, padx=12, pady=12)

        # Primary CTA — large Start
        self._start_btn = tk.Button(
            inner,
            text="▶  START",
            command=self._start_hub,
            font=("Segoe UI", 14, "bold"),
            bg=C_PHOSPHOR_DIM,
            fg="#0a0908",
            activebackground=C_PHOSPHOR,
            activeforeground="#0a0908",
            disabledforeground=C_MUTED,
            relief=tk.FLAT,
            bd=0,
            padx=28,
            pady=12,
            cursor="hand2",
        )
        self._start_btn.pack(side=tk.LEFT)

        self._stop_btn = tk.Button(
            inner,
            text="STOP",
            command=self._stop_hub,
            font=("Segoe UI", 12, "bold"),
            bg=C_CONCRETE_LIT,
            fg=C_TEXT_DIM,
            activebackground=C_DANGER,
            activeforeground=C_TEXT,
            disabledforeground=C_MUTED,
            relief=tk.FLAT,
            bd=0,
            padx=22,
            pady=12,
            state=tk.DISABLED,
            cursor="hand2",
        )
        self._stop_btn.pack(side=tk.LEFT, padx=(10, 0))

        hint = tk.Label(
            inner,
            text="Saves config, opens CAN, broadcasts telemetry + NMEA to the phone IP.",
            bg=C_CONCRETE_MID,
            fg=C_TEXT_DIM,
            font=("Segoe UI", 9),
            wraplength=360,
            justify=tk.LEFT,
        )
        hint.pack(side=tk.LEFT, padx=(16, 0))

        self._lan_var = tk.StringVar(value=f"Laptop  {lan_ip()}")
        tk.Label(
            inner,
            textvariable=self._lan_var,
            bg=C_CONCRETE_MID,
            fg=C_HAZARD,
            font=("Consolas", 10),
        ).pack(side=tk.RIGHT)

    def _build_gps_panel(self, parent: ttk.Frame) -> None:
        box = ttk.Labelframe(parent, text="  GPS HEALTH  ", padding=12)
        box.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 8))
        self._gps_fix = tk.StringVar(value="No fix")
        ttk.Label(box, textvariable=self._gps_fix, style="GPS.TLabel").grid(row=0, column=0, sticky="w")
        self._gps_coords = tk.StringVar(value="—")
        ttk.Label(box, textvariable=self._gps_coords, style="GPS.TLabel").grid(
            row=0, column=1, sticky="w", padx=(16, 0)
        )
        fields = [
            ("Speed", "_gps_speed"),
            ("Heading", "_gps_heading"),
            ("Sats", "_gps_sats"),
            ("Quality", "_gps_quality"),
            ("ATX", "_gps_atx"),
            ("NMEA sent", "_gps_nmea"),
        ]
        for i, (lbl, attr) in enumerate(fields):
            ttk.Label(box, text=lbl, foreground=C_MUTED).grid(
                row=1 + i // 3, column=(i % 3) * 2, sticky="w", pady=3
            )
            var = tk.StringVar(value="—")
            setattr(self, attr, var)
            ttk.Label(box, textvariable=var, style="Metric.TLabel").grid(
                row=1 + i // 3, column=(i % 3) * 2 + 1, sticky="w", padx=(6, 18)
            )

    def _build_can_panel(self, parent: ttk.Frame) -> None:
        box = ttk.Labelframe(parent, text="  CAN ADAPTER  ", padding=10)
        box.grid(row=1, column=0, sticky="nsew", padx=(0, 6))
        rows = [
            ("COM port", "can_interface", "combo"),
            ("Bitrate", "can_bitrate", "combo_bitrate"),
            ("USB baud", "tty_baud", "combo_baud"),
            ("Profile", "sprayer_profile", "combo_profile"),
        ]
        self._com_combo: ttk.Combobox | None = None
        for r, (lbl, key, kind) in enumerate(rows):
            ttk.Label(box, text=lbl).grid(row=r, column=0, sticky="w", pady=3)
            if kind == "combo":
                self._com_combo = ttk.Combobox(box, textvariable=self._var(key), width=18)
                self._com_combo.grid(row=r, column=1, sticky="ew", pady=3)
            elif kind == "combo_bitrate":
                ttk.Combobox(
                    box,
                    textvariable=self._var(key, "250000"),
                    values=["125000", "250000", "500000"],
                    width=18,
                ).grid(row=r, column=1, sticky="ew", pady=3)
            elif kind == "combo_baud":
                ttk.Combobox(
                    box,
                    textvariable=self._var(key, "2000000"),
                    values=["115200", "230400", "921600", "2000000"],
                    width=18,
                ).grid(row=r, column=1, sticky="ew", pady=3)
            elif kind == "combo_profile":
                ttk.Combobox(
                    box,
                    textvariable=self._var(key, "jd_616r"),
                    values=["jd_616r", "goldacres_grc", "generic"],
                    width=18,
                    state="readonly",
                ).grid(row=r, column=1, sticky="ew", pady=3)

        box.columnconfigure(1, weight=1)
        btns = ttk.Frame(box)
        btns.grid(row=len(rows), column=0, columnspan=2, sticky="ew", pady=(10, 0))
        ttk.Button(btns, text="Save + apply CAN", command=self._save_apply_can).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(btns, text="Restart CAN", command=self._restart_can).pack(side=tk.LEFT)
        ttk.Button(btns, text="Refresh COM", command=self._refresh_ports).pack(side=tk.LEFT, padx=(6, 0))

    def _build_net_panel(self, parent: ttk.Frame) -> None:
        box = ttk.Labelframe(parent, text="  WIFI / TABLET  ", padding=10)
        box.grid(row=1, column=1, sticky="nsew", padx=(6, 0))

        ttk.Label(box, text="Phone IP").grid(row=0, column=0, sticky="w", pady=3)
        ttk.Entry(box, textvariable=self._var("unicast_client"), width=22).grid(
            row=0, column=1, sticky="ew", pady=3
        )
        ttk.Label(box, text="NMEA port").grid(row=1, column=0, sticky="w", pady=3)
        ttk.Entry(box, textvariable=self._var("nmea_udp_port", "9999"), width=22).grid(
            row=1, column=1, sticky="ew", pady=3
        )

        ttk.Label(box, text="Lat/lon decode").grid(row=2, column=0, sticky="w", pady=3)
        self._latlon_combo = ttk.Combobox(
            box,
            textvariable=self._var("nmea_latlon_mode", "jd_atx"),
            values=["jd_atx", "j1939", "raw"],
            width=20,
            state="readonly",
        )
        self._latlon_combo.grid(row=2, column=1, sticky="ew", pady=3)
        self._latlon_combo.bind("<<ComboboxSelected>>", self._on_latlon_mode_change)
        ttk.Label(
            box,
            text="616R StarFire: leave at jd_atx (same math as j1939 — uint32 − 210°). "
            "Lon near −90 was a signed-int bug, not this dropdown.",
            style="Hint.TLabel",
            wraplength=300,
        ).grid(row=3, column=0, columnspan=2, sticky="w")
        self._latlon_active = tk.StringVar(value="Active decode: —")
        ttk.Label(box, textvariable=self._latlon_active, style="Hint.TLabel").grid(
            row=4, column=0, columnspan=2, sticky="w", pady=(2, 0)
        )

        self._nmea_var = tk.BooleanVar(value=self._cfg.get("nmea_relay", True))
        ttk.Checkbutton(box, text="NMEA relay to phone", variable=self._nmea_var).grid(
            row=5, column=0, columnspan=2, sticky="w", pady=(6, 2)
        )

        # Quiet defaults — not needed for tablet GPS day-to-day
        self._var("udp_port", self._cfg.get("udp_port", 5578))
        self._var("multicast_group", self._cfg.get("multicast_group", "none"))
        self._var("can_rx_max_hz", self._cfg.get("can_rx_max_hz", 50))

        btns = ttk.Frame(box)
        btns.grid(row=6, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        ttk.Button(btns, text="Save + apply network", command=self._apply_network).pack(
            side=tk.LEFT
        )
        box.columnconfigure(1, weight=1)

    def _build_sniff_panel(self, parent: ttk.Frame) -> None:
        box = ttk.Labelframe(parent, text="  SNIFF / RECORD (optional)  ", padding=10)
        box.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(8, 0))

        ttk.Label(
            box,
            text="Writes frames.csv under the folder below. Live tablet GPS does not use this.",
            style="Hint.TLabel",
            wraplength=720,
        ).grid(row=0, column=0, columnspan=4, sticky="w", pady=(0, 6))

        ttk.Label(box, text="Save to").grid(row=1, column=0, sticky="w", pady=3)
        ttk.Entry(box, textvariable=self._var("recordings_dir"), width=48).grid(
            row=1, column=1, sticky="ew", pady=3, padx=(4, 6)
        )
        ttk.Button(box, text="Browse…", command=self._browse_recordings).grid(row=1, column=2, sticky="w")

        ttk.Label(box, text="Filter").grid(row=2, column=0, sticky="w", pady=3)
        rf_frame = ttk.Frame(box)
        rf_frame.grid(row=2, column=1, sticky="w", pady=3, padx=(4, 0))
        self._record_preset = ttk.Combobox(
            rf_frame,
            textvariable=self._var("sniff_mode", "616r"),
            values=[p[0] for p in RECORD_PRESETS],
            width=14,
            state="readonly",
        )
        self._record_preset.pack(side=tk.LEFT)
        self._record_preset.bind("<<ComboboxSelected>>", self._on_record_preset_change)
        self._advanced_btn = ttk.Button(rf_frame, text="Advanced…", command=self._open_advanced_filter)
        self._advanced_btn.pack(side=tk.LEFT, padx=(6, 0))

        ttk.Label(box, text="Label").grid(row=3, column=0, sticky="w", pady=3)
        ttk.Entry(box, textvariable=self._var("record_label", "hub_sniff"), width=24).grid(
            row=3, column=1, sticky="w", pady=3, padx=(4, 0)
        )

        btns = ttk.Frame(box)
        btns.grid(row=4, column=0, columnspan=3, sticky="w", pady=(8, 0))
        self._rec_start_btn = ttk.Button(btns, text="Start sniff", command=self._start_sniff)
        self._rec_start_btn.pack(side=tk.LEFT, padx=(0, 6))
        self._rec_stop_btn = ttk.Button(btns, text="Stop sniff", command=self._stop_sniff, state=tk.DISABLED)
        self._rec_stop_btn.pack(side=tk.LEFT, padx=(0, 12))
        self._rec_status = tk.StringVar(value="Idle")
        ttk.Label(btns, textvariable=self._rec_status, style="Hint.TLabel").pack(side=tk.LEFT)

        box.columnconfigure(1, weight=1)

    def _build_live_panel(self, parent: ttk.Frame) -> None:
        box = ttk.Labelframe(parent, text="  LIVE BUS  ", padding=10)
        box.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        self._live_can = tk.StringVar(value="—")
        self._live_speed = tk.StringVar(value="—")
        self._live_stats = tk.StringVar(value="—")
        for i, (lbl, var) in enumerate(
            [("CAN", self._live_can), ("Speed", self._live_speed), ("Stream", self._live_stats)]
        ):
            ttk.Label(box, text=lbl, foreground=C_MUTED).grid(row=0, column=i * 2, sticky="w")
            ttk.Label(box, textvariable=var, style="Metric.TLabel").grid(
                row=0, column=i * 2 + 1, sticky="w", padx=(4, 20)
            )
        nodes = ttk.Frame(box)
        nodes.grid(row=1, column=0, columnspan=6, sticky="w", pady=(10, 0))
        for key, label in NODE_KEYS:
            cell = ttk.Frame(nodes)
            cell.pack(side=tk.LEFT, padx=(0, 14))
            dot = tk.Label(cell, text="●", bg=C_CONCRETE, fg=C_MUTED, font=("Segoe UI", 11))
            dot.pack(side=tk.LEFT)
            ttk.Label(cell, text=label).pack(side=tk.LEFT, padx=(3, 0))
            self._node_labels[key] = dot

    def _build_log_panel(self, parent: ttk.Frame) -> None:
        box = ttk.Labelframe(parent, text="  LOG  ", padding=8)
        box.pack(fill=tk.BOTH, expand=True, pady=(10, 0))
        self._log = tk.Text(
            box,
            height=7,
            bg=C_LOG_BG,
            fg=C_PHOSPHOR_DIM,
            insertbackground=C_TEXT,
            relief=tk.FLAT,
            font=("Consolas", 9),
            wrap=tk.WORD,
        )
        self._log.pack(fill=tk.BOTH, expand=True)

    def _build_footer(self, parent: ttk.Frame) -> None:
        row = ttk.Frame(parent, style="Slab.TFrame")
        row.pack(fill=tk.X, pady=(8, 0))
        ttk.Label(
            row,
            text=f"Config  {config_path()}",
            style="Sub.TLabel",
            wraplength=520,
        ).pack(side=tk.LEFT)
        ttk.Label(
            row,
            text="UI elements © Fox Rockett Studio (licensed)",
            style="Sub.TLabel",
        ).pack(side=tk.RIGHT)

    def _set_running_ui(self, running: bool) -> None:
        self._running = running
        if running:
            self._status_var.set("RUNNING")
            self._status_lbl.configure(style="StatusRun.TLabel")
            self._status_dot.configure(fg=C_PHOSPHOR)
            self._start_btn.configure(
                state=tk.DISABLED,
                text="RUNNING",
                bg=C_CONCRETE_LIT,
                fg=C_MUTED,
            )
            self._stop_btn.configure(
                state=tk.NORMAL,
                bg=C_DANGER,
                fg=C_TEXT,
                activebackground=C_DANGER_LIT,
            )
        else:
            self._status_var.set("STOPPED")
            self._status_lbl.configure(style="StatusStop.TLabel")
            self._status_dot.configure(fg=C_SODIUM)
            self._start_btn.configure(
                state=tk.NORMAL,
                text="▶  START",
                bg=C_PHOSPHOR_DIM,
                fg="#0a0908",
            )
            self._stop_btn.configure(
                state=tk.DISABLED,
                bg=C_CONCRETE_LIT,
                fg=C_TEXT_DIM,
            )

    def _on_record_preset_change(self, _event=None) -> None:
        mode = self._var("sniff_mode").get().strip()
        if mode == "custom":
            self._advanced_btn.configure(state=tk.NORMAL)
            return
        self._advanced_btn.configure(state=tk.DISABLED)
        preset = preset_record_filter(mode)
        if preset is not None:
            self._record_filter = normalize_record_filter(preset)

    def _open_advanced_filter(self) -> None:
        self._var("sniff_mode").set("custom")

        def _saved(cfg: dict) -> None:
            self._record_filter = cfg
            self._append_log(
                f"Record filter: {len(cfg.get('categories', []))} categories, "
                f"{len(cfg.get('nodes', []))} nodes, {len(cfg.get('pgns', []))} PGNs"
            )
            self._save_config_file()
            if self._service.running:
                ok, msg = self._service.apply_record_filter()
                self._append_log(msg if ok else f"Error: {msg}")

        RecordFilterDialog(self, self._record_filter, _saved)

    def _browse_recordings(self) -> None:
        initial = self._var("recordings_dir").get().strip() or str(default_recordings_dir())
        path = filedialog.askdirectory(title="Recordings folder", initialdir=initial or None)
        if path:
            self._var("recordings_dir").set(path)

    def _start_sniff(self) -> None:
        self._save_config_file()
        if not self._service.running:
            messagebox.showinfo("Sniff", "Press START on the hub first")
            return
        label = self._var("record_label").get().strip() or "hub_sniff"
        ok, msg = self._service.start_record(label)
        if ok:
            self._recording = True
            self._rec_start_btn.configure(state=tk.DISABLED)
            self._rec_stop_btn.configure(state=tk.NORMAL)
            folder = self._var("recordings_dir").get().strip() or str(default_recordings_dir())
            self._rec_status.set(f"Recording → {folder}")
        else:
            messagebox.showerror("Sniff", msg)

    def _stop_sniff(self) -> None:
        ok, msg = self._service.stop_record()
        self._recording = False
        self._rec_start_btn.configure(state=tk.NORMAL)
        self._rec_stop_btn.configure(state=tk.DISABLED)
        self._rec_status.set("Idle" if ok else msg)

    def _load_form(self) -> None:
        c = self._cfg
        mapping = {
            "can_interface": c.get("can_interface", "COM2"),
            "can_bitrate": c.get("can_bitrate", 250000),
            "tty_baud": c.get("tty_baud", 2000000),
            "sprayer_profile": c.get("sprayer_profile", "jd_616r"),
            "sniff_mode": c.get("sniff_mode", "616r"),
            "udp_port": c.get("udp_port", 5578),
            "multicast_group": c.get("multicast_group", "none"),
            "unicast_client": c.get("unicast_client", ""),
            "nmea_udp_port": c.get("nmea_udp_port", 9999),
            "can_rx_max_hz": c.get("can_rx_max_hz", 50),
            "nmea_latlon_mode": c.get("nmea_latlon_mode", "jd_atx"),
            "recordings_dir": c.get("recordings_dir") or str(default_recordings_dir()),
            "record_label": c.get("record_label", "hub_sniff"),
        }
        for k, v in mapping.items():
            self._var(k, v).set(str(v))
        self._record_filter = normalize_record_filter(c.get("record_filter"))
        self._nmea_var.set(bool(c.get("nmea_relay", True)))
        self._on_record_preset_change()
        self._refresh_ports()
        self._set_running_ui(False)

    def _form_config(self) -> dict:
        def _int(key: str, default: int) -> int:
            try:
                return int(self._var(key).get().strip())
            except ValueError:
                return default

        mode = self._var("sniff_mode").get().strip() or "616r"
        rf = self._record_filter
        if mode != "custom":
            preset = preset_record_filter(mode)
            if preset is not None:
                rf = preset

        from gps_bridge_lib import normalize_latlon_mode

        latlon = normalize_latlon_mode(self._var("nmea_latlon_mode").get())

        return {
            "can_interface": self._var("can_interface").get().strip() or "COM2",
            "can_bitrate": _int("can_bitrate", 250000),
            "tty_baud": _int("tty_baud", 2000000),
            "sprayer_profile": self._var("sprayer_profile").get().strip() or "jd_616r",
            "sniff_mode": mode,
            "record_filter": rf,
            "udp_port": _int("udp_port", 5578),
            "multicast_group": self._var("multicast_group").get().strip() or "none",
            "unicast_client": self._var("unicast_client").get().strip(),
            "nmea_relay": self._nmea_var.get(),
            "nmea_udp_port": _int("nmea_udp_port", 9999),
            "nmea_latlon_mode": latlon,
            "can_rx_max_hz": _int("can_rx_max_hz", 50),
            "recordings_dir": self._var("recordings_dir").get().strip()
            or str(default_recordings_dir()),
            "record_label": self._var("record_label").get().strip() or "hub_sniff",
            "can_rx_only": True,
            "authority": "OBSERVE",
            "web_enabled": False,
        }

    def _save_config_file(self) -> None:
        self._cfg = self._form_config()
        self._record_filter = normalize_record_filter(self._cfg.get("record_filter"))
        save_config(self._cfg)
        self._service.merge_config(self._cfg)

    def _refresh_ports(self) -> None:
        ports = list_com_ports()
        if self._com_combo is not None:
            self._com_combo["values"] = ports
            cur = self._var("can_interface").get()
            if cur not in ports and ports:
                self._com_combo.set(ports[0])

    def _append_log(self, msg: str) -> None:
        def _write() -> None:
            self._log.insert(tk.END, msg + "\n")
            self._log.see(tk.END)

        self.after(0, _write)

    def _start_hub(self) -> None:
        self._save_config_file()
        mode = self._var("nmea_latlon_mode").get().strip() or "jd_atx"
        ok, msg = self._service.start(self._cfg)
        self._append_log(msg)
        if ok:
            self._set_running_ui(True)
            self._lan_var.set(f"Laptop  {lan_ip()}")
            self._latlon_active.set(f"Active decode: {mode}")
            self._append_log(f"FEF3 lat/lon mode = {mode}")

    def _stop_hub(self) -> None:
        # Non-blocking: joining the hub thread on the Tk UI thread used to freeze STOP.
        if self._recording:
            self._service.stop_record()
            self._recording = False
            self._rec_start_btn.configure(state=tk.NORMAL)
            self._rec_stop_btn.configure(state=tk.DISABLED)
            self._rec_status.set("Idle")
        self._append_log("Stopping hub…")
        self._service.stop(wait=False)
        self._set_running_ui(False)

    def _save_apply_can(self) -> None:
        self._save_config_file()
        if self._service.running:
            ok, msg = self._service.apply_can()
            if not ok:
                messagebox.showerror("CAN", msg)
            else:
                self._append_log(msg)
        else:
            self._append_log("Config saved — press START to open CAN")

    def _restart_can(self) -> None:
        if not self._service.running:
            messagebox.showinfo("CAN", "Press START first")
            return
        ok, msg = self._service.apply_can()
        self._append_log(msg if ok else f"Error: {msg}")

    def _on_latlon_mode_change(self, _event=None) -> None:
        """Dropdown change must hit the live GpsBridge immediately when running."""
        self._save_config_file()
        mode = self._var("nmea_latlon_mode").get().strip() or "jd_atx"
        if self._service.running:
            ok, msg = self._service.apply_network()
            self._append_log(msg if ok else f"Lat/lon apply failed: {msg}")
            self._latlon_active.set(f"Active decode: {mode}")
        else:
            self._latlon_active.set(f"Will use: {mode} (press START)")
            self._append_log(f"Lat/lon decode set to {mode} — press START to use it")

    def _apply_network(self) -> None:
        self._save_config_file()
        mode = self._var("nmea_latlon_mode").get().strip() or "jd_atx"
        if not self._service.running:
            self._latlon_active.set(f"Will use: {mode} (press START)")
            self._append_log("Config saved — press START to apply network")
            return
        ok, msg = self._service.apply_network()
        if not ok:
            messagebox.showerror("Network", msg)
        else:
            self._latlon_active.set(f"Active decode: {mode}")
            self._append_log(msg)

    def _tick(self) -> None:
        snap = self._service.snapshot()
        if snap:
            t = snap.get("telemetry") or {}
            gps = snap.get("gps") or {}
            self._render_gps(gps, t, snap)
            self._render_live(t, snap)
        # Keep button state aligned if service dies externally
        if self._running != bool(self._service.running):
            self._set_running_ui(bool(self._service.running))
        self.after(REFRESH_MS, self._tick)

    def _render_gps(self, gps: dict, tel: dict, snap: dict) -> None:
        valid = gps.get("valid")
        live = snap.get("gps_live")
        mode = gps.get("latlon_mode") or self._var("nmea_latlon_mode").get() or "jd_atx"
        if valid and live:
            q = FIX_LABELS.get(gps.get("fix_quality"), "Fix")
            self._gps_fix.set(q)
        elif gps.get("latitude") is not None and not live:
            self._gps_fix.set("Stale")
        else:
            self._gps_fix.set("Waiting…" if tel.get("atx_alive") else "No ATX")
        if gps.get("latitude") is not None:
            lat = float(gps["latitude"])
            lon = float(gps["longitude"])
            self._gps_coords.set(f"{lat:.6f}, {lon:.6f}")
            # Signed-lon bug symptom (pre-fix hub): WA ~121°E showed as ~−98°.
            if -120.0 <= lon <= -80.0 and -45.0 <= lat <= -10.0:
                self._latlon_active.set(
                    f"Active decode: {mode}  ← lon≈{lon:.1f} still looks signed; rebuild hub"
                )
            else:
                self._latlon_active.set(f"Active decode: {mode}")
        else:
            self._gps_coords.set("—")
            if self._service.running:
                self._latlon_active.set(f"Active decode: {mode}")
        self._gps_speed.set(
            f"{gps['speed_kmh']:.1f} km/h" if gps.get("speed_kmh") is not None else "—"
        )
        self._gps_heading.set(
            f"{gps['heading_deg']:.1f}°" if gps.get("heading_deg") is not None else "—"
        )
        self._gps_sats.set(str(gps["satellites"]) if gps.get("satellites") is not None else "—")
        q = gps.get("fix_quality")
        self._gps_quality.set(FIX_LABELS.get(q, str(q)) if q is not None else "—")
        self._gps_atx.set("Alive" if tel.get("atx_alive") else "—")
        stats = snap.get("stats") or {}
        self._gps_nmea.set(str(stats.get("nmea_sent", 0)))

    def _render_live(self, t: dict, snap: dict) -> None:
        self._live_can.set(str(t.get("can_status", "—")))
        speed = t.get("speed_kmh")
        self._live_speed.set(f"{speed:.1f} km/h" if speed is not None else "—")
        stats = snap.get("stats") or {}
        self._live_stats.set(f"tel {stats.get('telemetry', 0)} · rx {stats.get('can_rx', 0)}")
        for key, lbl in self._node_labels.items():
            lbl.configure(fg=C_PHOSPHOR if t.get(key) else C_MUTED)

    def _on_close(self) -> None:
        if self._service.running or self._running:
            if not messagebox.askokcancel("Quit", "Stop hub and exit?"):
                return
            if self._recording:
                self._service.stop_record()
                self._recording = False
            self._service.stop(wait=True, timeout=3.0)
        self.destroy()


def main() -> int:
    if "--engine-child" in sys.argv:
        run_engine_child()
        return 0
    if "--console" in sys.argv:
        from isobus_wifi_hub import cmd_hub, load_config as lc

        return cmd_hub(lc())
    app = HubApp()
    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
