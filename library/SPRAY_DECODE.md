# Spray CAN Decode Library

**Human-readable field decode ledger** for PUFworks sniff / recorder / bench-ui work.

Machine-readable catalog (PGN filter, categories, watch SAs): `spray_pgn_library.py` → `library/spray_pgn_library.json`  
Session aggregates: `library/field_observations.json` (regenerate with `python scripts/compile_pgn_catalog.py`)  
Architecture & safety decisions: `JD_ISOBUS_MAP.md` · `SAFETY.md`

---

## Naming convention (read this first)

**Primary labels = John Deere Diagnostics Center controller names**, as shown on the display node list (`NAME.instance | 0x<SA> | <network>`). These are the ECUs on the bus — not the tractor model painted on the hood.

| Use this | Not this (context only) |
| :--- | :--- |
| **SRC** (Spray Rate Controller) | “616R”, “4600”, “CommandCenter” |
| **MNC** (Manifold / Nozzle Controller) | “ExactApply box”, “sprayer” |
| **GWC** (Gateway Controller) | “See & Spray gateway” (alias OK in notes) |
| **GRC.001** (GreenStar Rate Controller) | “Goldacres”, “G5”, “SF7500” |
| **BHC** (Boom Height Controller) | “BoomTrac”, “BH1” |
| **NZC** (Nozzle Controller) | “nozzle body” |
| **ATX** (AutoTrac) | “SF7500”, “GPS receiver” |
| **DISP** (Cab display / terminal) | “Gen 4”, “Gen 5” |

**Service-manual aliases** (TM174719) are noted in parentheses where they differ — e.g. **SRC ≈ PSSC** (primary solution system control). Do not use manual-only names as the headline label unless Diagnostics Center has not been checked yet.

**Legacy repo abbreviations** (`SR1`, `MNA`, `BH1`) appear in older CSVs and code paths. Treat them as deprecated aliases:

| Legacy | JD name |
| :--- | :--- |
| SR1 | SRC |
| MNA | MNC |
| BH1 | BHC |

**Platform context** (which bus tap, which sprayer profile) belongs in the **Session log** section per recording — not in element decode tables.

---

## How to maintain this document

1. **Capture** — OBSERVE sniff with `SET_SNIFF_MODE:spray` (see `README.md`).
2. **Analyze** — `python scripts/analyze_616r_session.py recordings/<id>` or helper scripts under `scripts/`.
3. **Merge stats** — `python scripts/compile_pgn_catalog.py recordings/<id> …`
4. **Decode** — When an element prefix + scale is confirmed against operator ground truth, add a row to **Decoded elements** below and bump `status` in `spray_pgn_library.py` if a new PGN/SA pair needs catalog promotion.
5. **Cross-check** — Diagnostics Center roster for live `0x<SA>` before trusting manual SA guesses.

Status legend:

| Status | Meaning |
| :--- | :--- |
| `confirmed` | Operator ground truth or repeatable bench capture |
| `likely` | Consistent across sessions; not operator-verified |
| `hypothesis` | Pattern suspected; needs field proof |
| `unknown` | Seen on wire; no decode |

---

## Controller roster (canonical)

Authoritative mapping: `JD_ISOBUS_MAP.md` §3.2, §12.3. Sniffer labels: `sniff_616r.py` → `SA_LABELS_616R`.

### See & Spray implement stack (IB1 / X119 tap)

| JD name | Manual alias | Typical SA (hex / dec) | PGNs of interest | Role |
| :--- | :--- | :--- | :--- | :--- |
| **GWC** | — | `0x94` / 148 | TBD | See & Spray gateway; bridges implement ↔ BoomTrac. **Never claim.** |
| **SRC** | PSSC | `0xE1` / 225 *(field)*; `0x17` / 023 *(manual)* | `0xEF00`, `0xFFF8`, `0xFFFB` | Solution rate, pressure mode, master/section authority |
| **MNC** | — | `0xD4` / 212 *(field)*; `0x68` / 104 | `0xCB00`, `0xEF00`, `0xE700` | ExactApply manifold; high-volume work messages |
| **NZC** | — | `0xCD` / 205 *(field, assigned)* | `0xFFF4`, … | Per-nozzle actuation (SA ephemeral per key cycle) |
| **BHC** | BCHU / BH1 | `0x8A` / 138 | TBD | BoomTrac height |
| **VPU** | — | `0xA2` family / 162 | TBD | Vision processing (dynamic claim pool) |
| **JD_SEC** | — | `0xF7` / 247 | `0xCB00` | Section-control peer traffic |
| **ATX** | — | `0x1C` / 028 | `0xFEF1`, `0xFEE8`, `0xFFFF` | Speed / steering context |
| **DISP** | — | `0xF0` / 240, `0x26` / 038 | `0xEF00`, `0xE600` | Cab terminal; TC server / VT transport |

> **Field note (2026-06-11):** X119 implement tap on a See & Spray machine showed **no GWC `0x94` frames** in two OBSERVE sessions. SRC appeared at **`0xE1`**, not `0x17`. Always verify SA from Diagnostics Center for the machine under test.

### GreenStar rate path (GRC.001)

| JD name | SA | PGNs | Role |
| :--- | :--- | :--- | :--- |
| **GRC.001** | `0xCC` / 204 | `0xEF00`, `0xCB00`, PGN 160 (`0xA0`) | Raven fast-close rate valve + section valve bank (open implement controller) |

PUFVision / PUFworks **commands** GRC via DDI 141 (sections) and DDI 157 (rate) when profile `goldacres_grc`. Decode tables for GRC EF00 elements are validated on bench (`gatest_11` / `gatest_12`).

---

## Traffic categories

Aligned with `spray_pgn_library.py` categories and bench-ui toggles:

| Category | What belongs here | Primary controllers |
| :--- | :--- | :--- |
| `gps_motion` | Speed, position, heading, yaw | ATX, ENG `0x00` |
| `rate_section` | TC process data, DDI 141/157/158, section bitmap, MNC work msgs | SRC, MNC, GRC.001, JD_SEC |
| `flow_pressure` | Flow meter, line/tank pressure, pump | SRC, GRC.001 |
| `boom_height` | BoomTrac / wing height | BHC |
| `spray_proprietary` | EF00 element streams, undocumented PF/PS | SRC, MNC, DISP, NZC |

**Section control (SCS)** is not a separate recorder filter. It lives inside `rate_section` + proprietary EF00 from SRC/MNC. For analysis, prioritize `(MNC, 0xCB00)`, `(JD_SEC, 0xCB00)`, `(SRC, 0xEF00)`.

---

## Decoded elements

Format: `prefix` = first bytes of EF00 (or CB00) payload; scale applies to little-endian u16 at documented offset unless noted.

### SRC — PGN `0xEF00` (Spray Rate Controller)

Observed SA: **`0xE1`** (See & Spray field sessions 2026-06-11).

| Element prefix | Status | Decode | Example payload | Session / notes |
| :--- | :--- | :--- | :--- | :--- |
| `4F0101` | **confirmed** | Target rate: `u16[3:5] / 10` → L/ha | `4F01015203002AE1` → **85.0** | `616r_observe_2`; operator targets 85 & 60 L/ha |
| `F43401` | **confirmed** | Rate vs pressure mode selector. `BE u16[3:5] / 4.096` → kPa when ≥ 256; else rate mode | `F43401100000FFFF` → **1000 kPa**; `F43401000100FFFF` → rate mode | `616r_observe_2` +132–138 s operator switched to 1000 kPa preset |
| **`F43400`** | **confirmed** | **Transport-mode counterpart** to `F43401` — boom off / road travel; static `BE u16[3:5] ≈ 0x1000` | `F43400100000FFFF` | `616r_transport` 2026-06-15; ~12% EF00; pairs with `F10E1C` |
| `F43401010000FFFF` | **likely** | Transitional frame during mode switch (pressure takeover) | seen at +138.1 s with `4F0101` clearing | Pair with operator action |
| `4F0601` | hypothesis | Master OFF `…FF00` / ON `…FF01` (same grammar as GRC) | — | Not operator-verified on SRC |
| `4F0B06` | **likely** | **Manual / IBS section control** (element `0x0B`, sub `0x06`) | Two pathways below — `observe_4_sections` |
| `4F0B0602…` | **confirmed** | **Section bitmap** — baseline all-on `4F0B06025555D53F`; toggle flips **one nibble** in byte **4, 5, or 6** per section | Single-toggle calibration `616r_R5`…`616r_L5` (2026-06-11) |
| `4F0B06FFxxxx…` | **confirmed** | **Toggle command**; byte **[4]** = group key (4 groups for 11 sections); bytes **[5:8]** = `010000` or `020000` | Not 1:1 alone — pair with `0602` bitmap |
| `4F0B06FFD1010000` | **confirmed** | Session preamble / idle | Present at start of every manual section capture |
| `4F0B060002000000` / `4F0B06010601010B` | hypothesis | Session bookends / mode preamble | Present entire `observe_4_sections` |
| `4F1401` / `4F3601` / `4F1C01` | **likely** | High-rate spray telemetry; `4F1401` u16[3:5] ~1 Hz pairs with `4F3601` | `616r_spray_asc`; 994+ frames/session |
| `F10E4C` | **likely** | Pressure telemetry in **rate mode** (`F43401` rate path) | Older sessions at 85 L/ha |
| **`F10E1C`** | **confirmed** | **Transport-mode** F10E family — replaces `F10E4C`/`F10E5C` off boom | `616r_transport` 2026-06-15; ~15% EF00; pairs with `F43400`; byte6-7 counter |
| **`F10E5C`** | **confirmed** | Pressure telemetry in **pressure mode** (1000 kPa) — **replaces F10E4C** when `F43401100000FFFF` active | `616r_spray_live` 2026-06-15; ~15% EF00; byte6-7 counter ticks ~1 Hz |
| `F70400` | unknown | Idle / session filler (~15% EF00) `F70400FFFFFFFFFF` | All sessions; protobuf score **15** (not protobuf) |
| `F00DFF` / `F225FA` / `F009FF` | hypothesis | Idle markers / bookends | ~12% + ~5% |
| **`F22500`** | **likely** | Transport idle filler `F22500FFFFFFFFFF` | `616r_transport`; alongside `F43400`/`F10E1C` |
| Full prefix table | see catalog | 17 element prefixes, **69%** classified | **`library/src_ef00_catalog.json`** |

**Scripts:** `python scripts/decode_src_ef00.py recordings/<session>` · `python scripts/decode_field_library.py`

**Corrections logged:**

- Rate scale is **`/10`**, not `/100` (would read 8.5 instead of 85).
- `4F01010000002AE1` at +138 s is **pressure-mode idle**, not “operator set rate to zero”.

---

### GRC.001 — PGN `0xEF00` (GreenStar Rate Controller)

Observed SA: **`0xCC`**. Decoder: `bus_engine.py` → `_parse_grc_ef00()`.

| Element prefix | Status | Decode | Notes |
| :--- | :--- | :--- | :--- |
| `4F0101` | **confirmed** | `u16[3:5] / 10` → L/ha (applied / display rate) | Same element family as SRC |
| `4F0601` | **confirmed** | `FF00` master OFF; `FF01` master ON | |
| `4F0B020200050000` | **confirmed** | Manual timer exit → all sections OFF | gatest_12 |
| `4F0B020201050000` | **confirmed** | Manual all-on reset | |
| `4F0B02020105XX00` | **confirmed** | Per-section manual toggle (debounced) | XX maps L1/L2/C/R2/R1 |
| `4F0B0201020201XX` | likely | Legacy auto-mode side select | ga_test5 |

**ISOBUS TC path (DDI, not EF00):**

| DDI | Status | Decode | Direction |
| :--- | :--- | :--- | :--- |
| `0x008D` (141) | **confirmed** | Section control state bitmask | PUFworks TX → GRC |
| `0x009D` (157) | **confirmed** | Target rate (suppressed on some profiles) | PUFworks TX → GRC |
| `0x009E` (158) | **confirmed** | Applied rate feedback | GRC → bus |

---

### MNC — PGN `0xCB00` (Manifold / Nozzle Controller)

Observed SA: **`0xD4`**. Highest frame count on See & Spray field tap (~84k frames / session).

**Grammar (2026-06-12, `library/mnc_cb00_map.json`):** byte0 = lane key (`0x03+n×0x10`, L5→R5); bytes1-3 = suffix (`110200` spray ~69%, `00A4xx` ASC turn). Prefix4 e.g. `93110200`. ASC cascade: `9311→8311→7311→5311`.

| Pattern (first 4 bytes) | Status | Decode | Notes |
| :--- | :--- | :--- | :--- |
| `0xD4 → 0xF7` CB00 | **confirmed** | Work message class (`0CCBF7D4` arbitration) | PF `0xCB`; legacy logs say “SR1” — source is **MNC** |
| `1300A4…` bursts | **likely** | Active spray / application work state | Dominates unique payloads during application (`observe_2`) |
| `1300A600` / `1300A500` / `1300A200` | **likely** | Active work variants during **headland turn** | Appear +355–370 s in `observe_3_long` while ASC sections off |
| `93110200` → `83110200` → `73110200` → `53110200` | **likely** | **ASC sequential section ON** on re-entry | Cascade +370–385 s in `observe_3_long`; operator deliberately angled headland to stagger section on |
| `03110200` / `13110200` / `23110200` / `F3100200` | **likely** | Idle / handshake / low-motion | Dominates straight-line and pre-turn windows |
| `031102…` (generic) | hypothesis | Idle family — exact byte semantics TBD | |

**Scripts / tools:** `decoder/decode_can.py`, `decoder/DECODER_FINDINGS.md` (legacy SR1 naming — treat as SRC/MNC), `scripts/analyze_op_notes.py` (operator-window correlation).

| Field | Status |
| :--- | :--- |
| Per-nozzle bitmap offset | unknown |
| Rate coupling inside CB00 | unknown |
| Relationship to JD_SEC `0xF7` CB00 | unknown |
| Map prefix nibble to section index | **likely** — see `mnc_cb00_map.json` lane table |
| ASC suffix at headland/slowdown | **confirmed** — `00A400`/`00A500`/`00A300` replace `110200` when speed drops | `616r_spray_live` +195–215 s; see `mnc_event_slowdown_20260615.json` |

**Bytes 4–7 (tail4) — correlated with speed (2026-06-15, `616r_spray_live`):**

Script: `python scripts/analyze_mnc_tail_window.py recordings/616r_spray_live` → `library/mnc_tail_spray_live_asc.json`

| Window | Speed (FEF1) | Dominant suffix6 | Dominant tail4 (bytes 4–7) | Notes |
| :--- | :--- | :--- | :--- | :--- |
| +120–190 s steady | **22.9** km/h | `110200` (51%) | `C0270900` u16 LE **0x27C0**; `55555555` fill | Balanced lane byte0 across L5–R5 |
| **+195–215 s slowdown** | **15.1** km/h (min **10.1**) | `110200` + **`00A500`/`00A400`/`00A300`** | **`00000000`** (43%); `C0270900`; **`01000000`** | Lane **0x13** (L4) **45%** of frames; new prefix4 **`1300A500`/`1300A400`** |
| +220–250 s recover | **24.9** km/h | `110200` returns; ASC suffixs linger | `00000000`; `C0270900` | `F3100200` summary idle increases |

**Verdict on tail4:** fixed **u16 scalars / counters**, not protobuf. `0x27C0` family tracks with spray-active lanes; **`00000000` tail rises with deceleration**; diverse u16 values (`0x5A88`, `0x3760`, …) during ASC are **per-lane metrics**, not wire tags. Protobuf probe scores ≥57 on 4-byte tails are **false positives** (see protobuf hunt below).

---

### MNC — PGN `0xEF00`

Observed SA: **`0xD4`**. Second-largest EF00 source on field tap (~14k frames).

| Element prefix | Status | Notes |
| :--- | :--- | :--- |
| *(all)* | unknown | Distinct from SRC EF00 mix; no confirmed elements yet |

---

### JD_SEC — PGN `0xCB00`

Observed SA: **`0xF7`**.

| Pattern | Status | Notes |
| :--- | :--- | :--- |
| CB00 traffic | **confirmed** | ~8.6k frames/session; section-control peer |
| Payload grammar | unknown | Compare against MNC CB00 timestamps |

---

### NZC — proprietary PGNs

Observed SA: **`0xCD`** (assigned).

| PGN | Status | Frames (observe_2) | Notes |
| :--- | :--- | :--- | :--- |
| `0xFFF4` | unknown | ~5.9k | Nozzle feedback candidate |

---

### DISP — cab terminal (`0xF0` + VT `0x26`)

Validated on **`616r_spray_live`** (2026-06-15). Script: `python scripts/decode_disp.py recordings/<session>`.

**SA `0xF0` — rebroadcast / process data (~35k frames / 5 min)**

| PGN | Rate | Prefix (3 byte) | Status | Role |
| :--- | :---: | :--- | :--- | :--- |
| `0xEF00` | ~10 Hz | **`F107CC`** | **likely** | GRC link heartbeat (`…00000000`; 0xCC = GRC SA) |
| `0xEF00` | ~10 Hz | **`F002CC`** | **likely** | TC/GRC presence (`…3030FFFF`) |
| `0xEF00` | ~10 Hz | **`F10FFF`** | **likely** | Display heartbeat (`F10FFFFFCFFFFFFF`) |
| `0xFFF8` | ~10 Hz | **`850400`** | **likely** | Static display block `850400FF…` |
| `0xFFF8` | ~5 Hz | **`9B007D`** | hypothesis | Secondary metric |
| `0xFFF4` | variable | **`650F00`** | hypothesis | Dominant chunk `650F0000…` (759 unique) |
| `0xFEF1` | ~10 Hz | — | **confirmed** | Wheel speed rebroadcast (same as implement tap) |

**SA `0x26` — VT transport**

| PGN | Rate | Prefix (3 byte) | Status | Role |
| :--- | :---: | :--- | :--- | :--- |
| `0xE600` | high | **`A83C04` / `A83E04` / `A83D04`** | **likely** | VT multipacket chunks (`A8xx0400` family) |
| `0xE600` | medium | **`A80804`** | **likely** | Lower-rate VT baseline |
| `0xE600` | burst | **`A84C14`** … | hypothesis | `A8xx1400` object-pool subfamily |

Catalog: **`library/disp_catalog.json`**. Filter E600 from spray-rate analysis; keep EF00 `F107CC`/`F002CC` as GRC/TC liveness.

---

### ATX — motion context

| PGN | Status | Decode |
| :--- | :--- | :--- |
| `0xFEF1` | **confirmed** | SPN 84: `u16[1:3] / 256` km/h (verify byte offset per capture) |
| `0xFEE8` | likely | Navigation speed fallback |
| `0xFFFF` | **confirmed** | JD-proprietary GNSS-quality multiplex (sub-msg `0x51` byte3 = satellites used). See GPS/motion section below. SA-gate to `0x1C` (DISP `0xF0` also emits `0xFFFF`). |

---

### BHC — boom height (IB1 / X119 tap)

Observed SA: **`0x8A`**.

| PGN | Status | Notes |
| :--- | :--- | :--- |
| `0xFF23` | unknown | Static `00FFFFFFFFFFFFFF` during +218–235 s boom-raise window in `observe_3_long` |
| `0xFED9` | unknown | Static `C0FFFFFFFFFFFFFF` same window |

> **Field note:** Operator centre-section raise (+221–231 s, `observe_3_long`) produced **no payload change** on BHC `0xFF23`/`0xFED9` at the X119 tap. Height telemetry may be on **BoomTrac / IB2** (BCHU) or an undecoded PGN — not disproved, just not visible here.

---

### Unknown controller — SA `0xBA` (provisional **AUX_E700**)

Dominant in long sessions (~53k frames aggregate). **99% PGN `0xE700`**. Also **`0xD5` SA213** (~25k frames, mostly EF00). **Identify on Diagnostics Center** — added to watch list as `AUX_E700` / `AUX_EF00` until named.

**Roster cleanup:** `python scripts/decode_field_library.py` → `library/bus_roster.json` (all SAs across 27 sessions).

---

## Shadow channel — `host_commanded_bitmap`

`shadow_channels.csv` column `host_commanded_bitmap` mirrors `bus_engine.py` → `jd_commanded_sections`, updated from **bytes 0–1 of any `PF=0xCB` RX frame** on `jd_616r` (not a clean DDI-141 parse).

| Value (hex) | Status | Interpretation |
| :--- | :--- | :--- |
| `0xFFFE` | **likely** | Brief **all sections ON** pulse — seen at +111.2 s (`observe_3_long`) when operator enabled all sections |
| `0x0013` | **likely** | **Minimal / ASC-off** section state — dominates headland +350–380 s |
| `0x1193`, `0x1183`, `0x1163`, … | hypothesis | Rapid stepping during manual section toggles — may be **MNC work-msg bytes**, not a stable JD section matrix |

**Do not** treat 10 Hz flicker as ground truth until MNC `0xCB00` grammar is decoded. Use operator timestamps + MNC prefix cascades for section events.

---

## PGN quick reference

| PGN (hex) | Name | Category | Controllers seen |
| :--- | :--- | :--- | :--- |
| `0xCB00` | TC process / section / work msgs | `rate_section` | MNC, JD_SEC, GRC.001 |
| `0xEF00` | JD proprietary process data | `spray_proprietary` | SRC, MNC, GRC.001, DISP |
| `0x00A0` | PGN 160 DDI process data | `rate_section` | GRC.001 |
| `0xFEF1` | Wheel-based speed | `gps_motion` | ATX, ENG |
| `0xE600` | VT / transport | `spray_proprietary` | DISP |
| `0xFFF8` | Proprietary | `spray_proprietary` | SRC |
| `0xE700` | Proprietary | `spray_proprietary` | MNC, SA `0xBA` (unidentified) |
| `0xFF23` | Proprietary | `boom_height` | BHC |
| `0xFED9` | Proprietary | `boom_height` | BHC |

Full machine list: `library/spray_pgn_library.json`.

---

## Field session log

Operator context and **which controllers were on the bus** — not tractor marketing names.

| Session ID | Bus tap | Profile | Sniff mode | Controllers confirmed alive | Key findings |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `20260611_110727_616r_observe_1` | IB1 X119 | `jd_616r` | `spray` | SRC `0xE1`, MNC `0xD4`, DISP `0xF0`, ATX `0x1C`, BHC `0x8A`, NZC `0xCD`, JD_SEC `0xF7` | ~97 s; no GWC `0x94`; MNC CB00 work traffic |
| `20260611_122653_616r_observe_2` | IB1 X119 | `jd_616r` | `spray` | Same roster | ~237 s active spray; SRC rate `/10`; pressure 1000 kPa via `F43401`; 8772 unique MNC CB00 payloads |
| `20260611_131017_616r_observe_3_long` | IB1 X119 | `jd_616r` | `616r` | SRC `0xE1`, MNC `0xD4`, DISP `0x26`/`0xF0`, ATX `0x1C`, BHC `0x8A`, NZC `0xCD`, JD_SEC `0xF7`; **SA `0xBA`** (unidentified, `0xE700`) | **453 s**, 507k frames; rate **85 L/ha** constant; operator-correlated ASC + manual section events (see below) |
| `20260611_140009_616r_observe_4_sections` | IB1 X119 | `jd_616r` | `616r` | Same core roster + `0xBA` | **84 s**, 86k frames; **manual mode, ASC OFF**, overlap respray; 11-section OFF cascade ×2 (soft keys then IBS) — see below |
| `20260611_141549_616r_R5` … `142706_616r_L5` | IB1 X119 | `jd_616r` | `616r` | SRC `0xE1` | 11× single-section toggle captures; **section map confirmed** → `section_map.json` |
| `616r_dir_R5` / `ibs_R5_fix` / `pair_R5R4` | IB1 X119 | `jd_616r` | `616r` | SRC | Direction, IBS vs soft-key, R5+R4 composite (`FD3F`) |
| `616r_asc_headland` / `spray_asc` | IB1 X119 | `jd_616r` | `616r` | MNC | ASC on MNC only; `spray_asc` steady state after +131 s |
| `20260615_095343_616r_spray_live` | IB1 X119 | `jd_616r` | `616r` | SRC, MNC, DISP | ~301 s; 60 L/ha, 1000 kPa; ASC slowdown +195–215 s; **`F10E5C`** pressure telemetry |
| `20260615_103325_616r_transport` | IB1 X119 | `jd_616r` | `616r` | SRC, MNC, DISP | ~710 s road transport ~56 km/h; **`F43400`/`F10E1C`/`F22500`** mode family; MNC **`110100`** dominant (not spray `110200`) |

### `observe_3_long` — operator notes vs bus (session-relative seconds)

| Operator time | Action | Bus correlate | Confidence |
| :--- | :--- | :--- | :--- |
| **+111 s** | R5, R4, R3 off → all sections on; slow | Shadow `0xFFFE` all-on pulse **+111.2 s**; bitmap stepping from +108 s; speed still ~23 km/h at +111 s, decel **+129–133 s** (min **8.3 km/h**) | Partial — all-on confirmed; per-section bits need CB00 decode; slowdown **lags** toggles |
| **+191–201 s** | Increased speed | FEF1 **21 → 25.4 km/h** at +200–201 s | **Confirmed** |
| **+221–231 s** | Centre section raise (whole boom) → auto height | Speed flat ~24 km/h; BHC `0xFF23`/`0xFED9` **unchanged** on X119 | Boom action **not visible** on this tap |
| **+350–380 s** | Headland turn; ASC re-entry cascade on bus | Speed **22 → 7.5 km/h** (apex ~+365 s); shadow dominated by `0x0013`; MNC CB00 turn prefixes `1300A600`/`A500`/`A200`; re-entry cascade **`9311→8311→7311→5311`**. **Physical section OFF not visible** when ExactApply active — bus correlate is geometry + MNC only. | **Strong (bus)** / **N/A (physical sections)** |

**Correlate with vision capture:** match `frames.csv` `timestamp_ms` to agronomy `session_epoch_ms.txt` in collector folders.

### Capture protocol — 11-section manual cascade (planned)

**Boom indexing (operator / Work Setup):** centre-outward — **L5 · L4 · L3 · L2 · L1 · C · R1 · R2 · R3 · R4 · R5** (11 sections).

**Cascade order (outside-in, right → left):** **R5 → R4 → R3 → R2 → R1 → C → L1 → L2 → L3 → L4 → L5**

Run **OFF cascade** then **ON cascade** (or OFF only, then reset all-on) with **~2–3 s pause** per section so MNC `0xCB00` prefix steps land in separable time bins.

**Suggested label:** `616r_observe_4_sections`

**Op-notes template** (session-relative seconds):

```
+0s   master ON, steady speed ~15–20 km/h, rate 85 (or hold constant)
+__s  START OFF cascade R5
+__s  R4 off
+__s  R3 off
… through L5
+__s  ALL ON (or START ON cascade L5→…→R5 if reversing)
+__s  END
```

**Expected bus signals** (from `observe_3_long`):

| Signal | Where | What to look for |
| :--- | :--- | :--- |
| MNC `0xCB00` prefix step | MNC `0xD4` | `9311` / `8311` / `7311`-style nibble cascade (same family as ASC headland re-entry) |
| Shadow `host_commanded_bitmap` | `shadow_channels.csv` | Stepping values + `0xFFFE` all-on; **noisy** — use as hint only |
| SRC `0xEF00` `4F0B…` | SRC `0xE1` | Possible manual toggle elements — compare to Goldacres GRC grammar |

**Decoder bit hypothesis** (11-section subset of SR1 15-section map, `decoder/decode_can.py`): R5=bit2 … C=bit7 … L5=bit12. **Unconfirmed on ExactApply** — this session should validate.

**After capture:**

```powershell
python scripts/compile_pgn_catalog.py recordings\<session_id>
python scripts/analyze_op_notes.py recordings\<session_id>
python scripts/analyze_section_cascade.py recordings\<session_id>
```

### Capture protocol — single-section toggle (planned calibration)

**Goal:** map SRC `4F0B06FF` byte `[4]` and `4F0B0602` bitmap bytes to one boom section each.

**Order (11 captures):** **R5 → R4 → R3 → R2 → R1 → C → L1 → L2 → L3 → L4 → L5**

**Each capture (~15–30 s):**

1. Master ON, manual mode, **section control OFF** (same as `observe_4_sections`).
2. Steady speed **~15–20 km/h** if possible; hold rate constant.
3. **Wait ~3 s** after recorder start (baseline).
4. Toggle **one section OFF** (soft key *or* IBS — **pick one path and stick to it for all 11 runs**; recommend **soft keys first** for consistency with phase A decode).
5. **~2–3 s** off.
6. Toggle **same section ON**.
7. **~3 s** then stop recorder.

**Label convention:**

```text
616r_sec_R5
616r_sec_R4
…
616r_sec_L5
```

**Launcher (repeat per section):**

```powershell
cd C:\Projects\PUFworks-isobus
.\scripts\field_sniff_616r.ps1 -Interface COM2 -SniffMode 616r -Label "616r_sec_R5" -Record
# stop after step 7; then R4, R3, …
```

**Op note per file (one line is enough):**

```text
section=R5  method=softkey  off=+5s  on=+8s
```

**Expected bus (from `observe_4_sections`):**

| Event | SRC `0xE1` EF00 |
| :--- | :--- |
| Section OFF | One new `4F0B06FFxxxx…` + one `4F0B0602` bitmap step |
| Section ON | Matching `FF` / bitmap restore toward `…FFFF…3F` |

**After all 11:** batch merge + per-file diff:

```powershell
python scripts/compile_pgn_catalog.py recordings\20260611_*_616r_sec_*
```

Then share the 11 folder names (or one combined op-notes block) — we build the R5–L5 lookup table from the single-step `FF` byte unique to each run.

### `observe_4_sections` — operator context & bus correlate

**Run conditions:** already-sprayed pass; **section control OFF** (manual mode — no ASC forcing overlap off); **85 L/ha**; speed **~17–19 km/h** steady.

**Procedure:** (1) display **soft-key** OFF cascade R5→L5; (2) pause; (3) **IBS multifunction lever** same cascade.

| Phase | Time (approx) | UI path | Bus correlate | Confidence |
| :--- | :--- | :--- | :--- | :--- |
| **A — soft keys** | **+0 – +27 s** | Run-page section soft keys | SRC `4F0B0602` bitmap steps ~1 s apart: `…5555D53F` → `…FFFFFF3F` at **+26.3 s**; paired SRC `4F0B06FF*` index cmds **+14.3 – +26.3 s** (11 unique `FF` payloads) | **Strong** |
| **Gap** | **+27 – +48 s** | Operator switch to lever | No new `0602` bitmap family | — |
| **B — IBS lever** | **+48 – +61 s** | Multifunction lever IBS | SRC `4F0B0602` restarts `…5555E53F` **+48.3 s** → `…AAAAEA3F` **+61.1 s**; paired `4F0B06FF*` **+48.3 – +61.1 s** (10 unique) | **Strong** |

**SRC `4F0B06FF*` index byte `[4]` first-seen (soft-key phase):** `F1, F9, FB, 7B, 9B, A3, A5, 25, 45, 4D, 4F` — **11 steps**.  
**IBS phase:** `E1, E5, E6, 26, 36, 3A, 3B, 8B, 8F, 90` — **10 steps** (one section toggle may have been skipped or merged).

**MNC `0xCB00`:** `5311`/`6311`/`7311`/`8311`/`9311` families present but **high churn throughout** — not separable per toggle in manual mode (unlike ASC headland re-entry in `observe_3_long`). **Prefer SRC `4F0B06` for section decode.**

**Shadow `host_commanded_bitmap`:** stepping `0x1193` → `0x1183` → … → `0x10F3` during phase A; **`0xFFFE`** all-on pulses at +1, +3, +7, +25–29, +59–67 s. Still **noisy** (CB00 bytes 0–1) — use as secondary hint only.

**IBS (Indexed Boom Section):** manual lever path emits the **same SRC EF00 element family** (`4F0B06`) as soft keys, with distinct `FF` index-byte values — confirms IBS is not a separate CAN node on IB1; it is routed through **SRC / PSSC**.

### Section map — SRC `4F0B06` (confirmed 2026-06-11)

Single-toggle captures (`616r_R5` … `616r_L5`). Machine-readable: `library/section_map.json`.

**Baseline (all sections ON):** `4F0B06025555D53F` · preamble `4F0B06FFD1010000`

| Section | Toggle `4F0B06FF…` | Group byte [4] | Toggle bitmap `4F0B0602…` | Bitmap delta |
| :--- | :--- | :---: | :--- | :--- |
| **R5** | `…F1010000` | `0xF1` | `…5555F53F` | byte6 `D5→F5` |
| **R4** | `…D9010000` | `0xD9` | `…5555DD3F` | byte6 `D5→DD` |
| **R3** | `…D3010000` | `0xD3` | `…5555D73F` | byte6 `D5→D7` |
| **R2** | `…51020000` | `0x51` | `…55D5D53F` | byte5 `55→D5` |
| **R1** | `…F1010000` | `0xF1` | `…5575D53F` | byte5 `55→75` |
| **C** | `…D9010000` | `0xD9` | `…555DD53F` | byte5 `55→5D` |
| **L1** | `…D3010000` | `0xD3` | `…5557D53F` | byte5 `55→57` |
| **L2** | `…51020000` | `0x51` | `…D555D53F` | byte4 `55→D5` |
| **L3** | `…F1010000` | `0xF1` | `…7555D53F` | byte4 `55→75` |
| **L4** | `…D9010000` | `0xD9` | `…5D55D53F` | byte4 `55→5D` |
| **L5** | `…D3010000` | `0xD3` | `…5755D53F` | byte4 `55→57` |

**FF group key (byte [4] + suffix) → sections:**

| `FF` payload tail | Sections |
| :--- | :--- |
| `F1 01 00 00` | R5, R1, L3 |
| `D9 01 00 00` | R4, C, L4 |
| `D3 01 00 00` | R3, L1, L5 |
| `51 02 00 00` | R2, L2 |

**Decode rule:** use **`4F0B0602` bytes 4–6** (0-indexed payload) as authoritative per-section identity; `4F0B06FF` selects group only.

**Geometry hint:** right wing toggles **byte 5–6**; left wing toggles **byte 4–5**; centre **byte 5** (`5D`).

**Field decode:** `python scripts/decode_section_bitmap.py recordings\<session_id>`

---

### Paddock validation — 2026-06-11 afternoon

| Session | Result |
| :--- | :--- |
| `616r_dir_R5` | OFF at **+5.4 s** → `…F53F` (soft-key R5). **No return to `D53F`** before stop — ON not captured or not held long enough. |
| `616r_ibs_R5_fix` | IBS OFF → `…**E5**3F` + `FF**E1**010000` — **different encoding** from soft-key `…F53F` / `0xF1`. |
| `616r_pair_R5R4` | **Composite confirmed:** +6.4 s `…F53F` (R5) → +10.8 s `…**FD**3F` (R5+R4). Byte6 accumulates `D5→F5→FD`. FF `F1` then `F9`. |
| `616r_asc_headland` | SRC bitmap **ALL_ON entire pass**. Turn +15–23 s: MNC `1300A500`/`A200`/`A400`. Speed **9.6–20.6 km/h**. Usable. |
| `616r_asc_headland_on` | Messy — speed **6.6–17.5 km/h**, weak `1300A5xx` turn family. Superseded by `616r_headland_on`. |
| `616r_spray_asc` | Headland first ~40 s (`9311` lead); **steady +131 s** speed **21.6–25.7 km/h**; SRC stays ALL_ON. |
| `616r_headland_on` | **Clean ASC headland re-run** (19.8 s). SRC **ALL_ON** @ 85 L/ha entire pass. Speed **4.6→17.9 km/h** ramp. Pre-turn (+0–12 s): MNC `1300A1/A2/A4/A5xx` burst. Turn (+12–22 s): `0311/1311/2311/3311` cascade + `F3100200`. Usable — matches `616r_asc_headland` pattern. |
| `616r_dir5_2` | R5 soft-key retry (23.3 s @ **21–24 km/h**). OFF **+7.5 s** → `…F53F` + FF `0xF1`; ON restore **+17.5 s** → `…D53F` + FF `0xD1` (~10 s OFF, ~6 s ON hold). Decode scripts previously hid repeat `D53F` — fixed. |
| `616r_pair_R5R4R3` | **Triple composite confirmed** (33 s). `D5→F5→FD→FF` byte6; FF `D1→F1→F9→FB→D1`. ALL_ON restore **+25.9 s**. Rule: byte6 OR-accumulates single-section OFF deltas (`+0x20` R5, `+0x08` R4, `+0x02` R3). |

**ASC vs manual:** Auto section control gates on **MNC `0xCB00`** (`9311→8311…` + `1300A5xx` in turns). **SRC `4F0B0602` unchanged** during ASC — do not use SRC bitmap for ASC section state.

**ExactApply override (field, 2026-06-11):** On headlands and overlap with ASC **ON**, boom **sections do not visibly turn off** — individual nozzle control (ExactApply / See & Spray) overrides classic section-valve ASC. MNC `0xCB00` cascades (`9311→8311…`, `1300A5xx`) are still on the bus, but **cannot** be voice-correlated to “section X just shut off” in the cab. Treat MNC as **work-state / ASC intent**, not physical section valve truth. For section ground truth use **manual mode, ASC OFF** (`observe_4`, single-toggle map) or **SRC `4F0B0602`**.

### Nozzle ↔ section geometry (Work Setup, 37.0 m boom)

From operator Section Setup (2026-06-11). **38.1 cm** spacing all sections. Machine file: `library/nozzle_section_map.json`.

| Section | Nozzles | Width | Nozzle index (1-based, L5 outboard = 1) |
| :--- | :---: | :---: | :--- |
| L5 | 9 | 342.9 cm | 1–9 |
| L4 | 10 | 381.0 cm | 10–19 |
| L3 | 8 | 304.8 cm | 20–27 |
| L2 | 8 | 304.8 cm | 28–35 |
| L1 | 9 | 342.9 cm | 36–44 |
| C | 9 | 342.9 cm | 45–53 |
| R1 | 9 | 342.9 cm | 54–62 |
| R2 | 8 | 304.8 cm | 63–70 |
| R3 | 8 | 304.8 cm | 71–78 |
| R4 | 10 | 381.0 cm | 79–88 |
| R5 | 9 | 342.9 cm | 89–97 |

**Total: 97 nozzles** per Work Setup. **Nozzle 1 = far left (L5 outboard)** — confirmed operator 2026-06-11. Right tip = nozzle **97** (R5 outboard).

### GPS / motion on X119 (live spray + export)

| PGN | SA | Rate | Content | Status |
| :--- | :--- | :---: | :--- | :--- |
| `0xFEF3` (65267) | **ATX `0x1C`** | ~5 Hz | Lat / lon | **On wire** — export via `decode_gps_track.py` |
| `0xFEE8` (65256) | **ATX `0x1C`** | ~5 Hz | **TCM attitude** — see byte layout below | **Confirmed** (`observe_3_long`) |
| `0xFEE6` | **ATX `0x1C`** | ~5 Hz | **Roll** — bytes 2–3 `/128` deg | **Likely** (stable ~12° in capture) |
| `0xFFFF` (65535) | **ATX `0x1C`** | ~5 Hz | **GNSS satellites used** — proprietary multiplex, sub-msg `0x51` byte3 (see below) | **Confirmed** |
| `0xFEF1` | **DISP `0xF0`** (+ others) | ~10 Hz | Wheel speed SPN 84 | **Confirmed** |
| `0xF029` (61481) | — | — | SSI2 pitch/roll (standard) | **Not on X119** |
| `0xF02A` (61482) | — | — | Yaw rate (standard) | **Not on X119** — derive from FEE8 heading Δt |
| `0xFEF5` | — | — | Heading | Not seen on X119 captures |
| `0x1F802` (129026) | — | — | SOG/COG rapid | Not seen on X119 captures |

**PGN `0xFEE8` byte layout (ATX / StarFire / pysobus 65256):**

| Bytes | Field | Decode |
| :---: | :--- | :--- |
| 0–1 | Heading | `u16 / 128` deg |
| 2–3 | Navigation speed | `u16 / 256` km/h (phantom when stationary — prefer `0xFEF1`) |
| 4–5 | Pitch (SPN 583) | `u16 / 128 − 210` deg |
| 6–7 | Altitude (SPN 580) | `u16 × 0.125 − 2500` m |

**PGN `0xFEE6` roll (field hypothesis):** bytes 2–3 `u16 / 128` deg (no −210 offset). Validated stable during straight + headland in `observe_3_long`; not in standard 65256 layout.

**Yaw rate:** no `0xF02A` on implement tap — `gps_bridge_lib` differentiates consecutive FEE8 headings (~5 Hz). Headland window in `observe_3_long`: roughly −17 to +6 deg/s.

**PGN `0xFFFF` (65535) — JD-proprietary GNSS-quality multiplex (ATX/StarFire `0x1C`):**

`can_id 0x18FFFF1C`, ~5 Hz, ~11k frames in `616r_spray_live`. `0xFFFF` is a multiplexed proprietary container; **byte0 selects a sub-message** (`0x51`/`0x52`/`0x53`/`0x54`/`0xA0`/`0xE0`, each ~1538 frames). The decodable one is sub-msg **`0x51`**:

| Byte | Field | Decode | Status |
| :---: | :--- | :--- | :--- |
| 0 | Sub-message selector | `0x51` | confirmed |
| 1–2 | Signature | constant `0x03 0x02` (use to validate) | confirmed |
| **3** | **Satellites used** | uint8 — feeds GGA field 7 / `$PANDA` field 7 | **confirmed** |
| 4–6 | Per-constellation sat counts (GPS/GLONASS/Galileo) | uint8 each; **fall together with byte3** during signal loss → counts, **not** DOP | likely |
| 7 | Fix/status flag (hypothesis) | mostly `0x01`; ticks `0x02`/`0x03`/`0x04` during headland turn — not mapped to GGA fix-quality (no ground truth) | hypothesis |

Satellite count range across 25+ sessions: **≈ 25–39**, slowly varying, drops during headland turns (`observe_3_long` +381 s: byte3=36 but byte4-6 collapse 9/5/8 as used-sats fall). Confirmed in `616r_spray_live`, `observe_3_long`, `spray_gps`, `transport`, and all single-section captures.

> **Gate to SA `0x1C`.** DISP `0xF0` also emits `0xFFFF` (different content) — only the ATX `0x1C` `0x51` sub-msg is the GNSS summary.

**HDOP / PDOP / VDOP — NOT on the X119 tap.** No NMEA-2000 GNSS DOP / sats-in-view fast packet (`129539`/`129540`) on this classic 250 kbps bus. Other ATX `0x1C` proprietary PGNs were checked and ruled out as DOP: `0xFAB3` (~5 Hz, two interleaved frames `0x10…`/`0x18…`) is fine position/velocity; `0xF010` is a per-frame rolling counter (+10000/frame); `0xFFFF` sub-msgs `0x52`/`0x53` carry high-entropy tails (checksum / fine data). DOP fields stay blank in the bridge — never faked.

**Implementation:** `gps_bridge_lib.decode_gnss_sats_ffff()` + `GpsBridge.update_from_frame` (PGN `0xFFFF`, SA `0x1C`) → `GpsFix.satellites`; `gps_bridge.py` replay + live filters now pass `0xFFFF` (SA-gated to `0x1C`). GGA/`$PANDA` already emit `satellites` when present; HDOP field left empty.

**Not on implement tap:** full vehicle-bus GPS roster may include more PGNs (incl. DOP) on **VB1** (Premium Server / MTG). X119 gives speed + position + **satellite count** for laptop/tablet export.

```powershell
python scripts/decode_gps_track.py recordings\<session_id> --geojson recordings\<session_id>\track.geojson
```

**Live bridge (AgOpenGPS / custom apps):**

```powershell
# AgIO: enable UDP first. Default NMEA -> 127.0.0.1:9999
python scripts/gps_bridge.py --interface COM2

# Custom JSON app on port 5577 (GpsFixV2: pitch, roll, yaw_rate, altitude)
python scripts/gps_bridge.py --interface COM2 --json-udp 127.0.0.1:5577

# Import library: scripts/gps_bridge_lib.py (GpsBridge, GpsFix, nmea_gga, …)
```

Outputs `gps_track.csv` (`timestamp_ms`, `latitude`, `longitude`, `speed_kmh`, `heading_deg`, `pitch_deg`, `roll_deg`, `yaw_rate_deg_s`, `altitude_m`). Open GeoJSON in QGIS; merge with agronomy via `timestamp_ms` ↔ `session_epoch_ms.txt`.

**FEF3 decode:** default `--latlon-mode jd_atx` (lat uses J1939 −210° offset). **Validate** first fix against a known paddock corner — adjust `--latlon-mode j1939|raw` if needed.

---

### ExactApply subnets (4 CAN legs, IB3–IB6)

From JD Help Center *ExactApply | Subnets* (left/right = facing forward):

| Subnet | CAN bus | Boom region | Help colour |
| :---: | :--- | :--- | :--- |
| **1** | IB3 | Far **left** | Green |
| **2** | IB4 | Left-of-centre | Yellow |
| **3** | IB5 | Right-of-centre | Orange |
| **4** | IB6 | Far **right** | Blue |

**Rules:** Subnet count varies along the boom. **Within each subnet**, the *first* nozzle body is **inboard** (closest to machine centre), not at the wing tip. MNC (`0xD4`) masters all four; NZC (`0xCD`) addresses are **ephemeral per power cycle** on each subnet.

**Hypothesis — subnet ↔ global nozzle** (Diagnostics nozzle-body pages **unavailable** post-update — see alternatives below):

| Subnet | Sections | Global nozzles |
| :---: | :--- | :--- |
| 1 | L5–L2 | 1–35 |
| 2 | L1, C | 36–53 |
| 3 | R1, R2 | 54–70 |
| 4 | R3–R5 | 71–97 |

Machine file: `library/nozzle_section_map.json` → `exactapply_subnets`.

### ExactApply nozzle body — physical layer (JD Help Center)

Each **NZC** (nozzle body) has an 8-pin connector and two parallel circuits:

| Pin | Function |
| :---: | :--- |
| 1 | Sync **Out** |
| 2 | CAN Hi Out |
| 3 | CAN Lo Out |
| 4 | Ground |
| 5 | Sync **In** |
| 6 | CAN Hi In |
| 7 | CAN Lo In |
| 8 | Power (12 V) |

**CAN** — daisy-chain **pass-through** on each subnet (In → body → Out). MNC masters IB3–IB6; NZC SAs assigned at **key-on**.

**Sync** — separate **series** circuit (not CAN pass-through). Two modes after ignition:

1. **Addressing Mode** — per subnet, signal from MNC hits **inboard** NZC first, then Sync Out → Sync In **outboard** along the chain. Each body learns its position.
2. **Sync Mode** — **15 Hz** heartbeat on same Sync path; keeps all NZCs on a common time base for solenoid pulse timing.

**Failure:** Power loss at one NZC **breaks Sync** at that point → all **outboard** NZCs on that subnet fault (inboard may still run).

### Three control layers (why ASC ≠ section OFF in cab)

| Layer | Count | Bus / node | What you see on X119 sniff |
| :--- | :---: | :--- | :--- |
| **Section** | 11 | SRC `0xE1` `EF00` | `4F0B0602` bitmap — manual/ASC *intent* |
| **Subnet** | 4 | MNC `0xD4`; IB3–IB6 | `0xCB00` work msgs, ASC cascades |
| **Nozzle** | 97 | NZC `0xCD`; per subnet | `0xFFF4` etc. — **actual** pulse control |

ExactApply runs the **nozzle layer**; section bitmap can stay ALL_ON while NZCs individually blank on headland/overlap. That is expected, not a sniff gap.

**Diagnostics gap (2026-06-11):** Recent CommandCenter update removed nozzle-body status / subnet install screens. Subnet boundary table stays **hypothesis** until validated another way.

**Alternatives without Diagnostics:**

| Method | Effort | Unlocks |
| :--- | :--- | :--- |
| **Keep section-frame split** (table above) | None | Sufficient for library + Pathway E whole-boom blanking |
| **Key-on sniff** ~60 s, `616r_full`, label `616r_keyon` | One ignition cycle | NZC address-assignment burst on wire |
| **NZC `0xFFF4` offline** on `observe_3` / `spray_asc` | Desk work | Actuation patterns vs speed/turn |
| **Passive fault** (if boom throws NZC fault) | None | Sync break → outboard NZCs on one subnet fault together |

Do **not** block integration on subnet roster confirmation.

---

### Paddock plan — next captures (after section map)

Priority order if time-limited:

| # | Label | ~dur | What to do | Unlocks |
| :---: | :--- | :---: | :--- | :--- |
| 1 | `616r_dir_R5` | 25 s | Soft-key: wait 3 s → **OFF R5 only** → hold 5 s → **ON R5** → stop. Note `off=+Xs on=+Ys`. | Confirm toggle bitmap = OFF vs ON direction |
| 2 | `616r_ibs_R5` | 25 s | Same via **IBS lever** only (R5 off/on). | IBS uses same `4F0B06` bytes as soft keys? |
| 3 | `616r_pair_R5R4` | 30 s | All on → **OFF R5** → **OFF R4** (no on between) → all on → stop. | Composite bitmap (multi-section) |
| 4 | `616r_cascade2` | 60 s | Full OFF cascade R5→L5 soft keys, **3 s per step**, voice/timestamp each. | Step-through validation vs `section_map.json` |
| 5 | `616r_asc_headland` | 90 s | **Section control ON**, short headland turn (like observe_3). | MNC `9311→5311` with known SRC baseline |
| 6 | `616r_spray_asc` | 3–5 min | Normal spray pass, ASC on, steady speed. | Live composite bitmap during ASC |

**Launcher (each):**

```powershell
cd C:\Projects\PUFworks-isobus
.\scripts\field_sniff_616r.ps1 -Interface COM2 -SniffMode 616r -Label "<label>" -Record
```

**After each:** `python scripts/decode_section_bitmap.py recordings\<folder>`

---

## Protobuf hunt results (2026-06-15)

Session: **`616r_spray_live`**. Checklist: `library/PROTOBUF_HUNT_CHECKLIST.md`. Raw log: `library/protobuf_hunt_spray_live.txt`.

| Priority | Target | Score | Frames | Verdict |
| :---: | :--- | :---: | :---: | :--- |
| 1 | MNC CB00 bytes 4–7 (`--offset 4`) | 89 (rare) / **57** (93110200) | 1 / 32 | **Not protobuf** — fixed u16 tail; correlate speed (above) |
| 2 | SRC `F70400` | **15** | 3845 | **Not protobuf** — constant `FF` padding |
| 3 | SRC `4F1401` tail (`--offset 6`) | **57** | 254 | **Not protobuf** — fixed `0x002A` trailer |
| 4 | SA `0xBA` `0xE700` | **17–19** | 613+ | **Not protobuf** — VT-chunk grammar (`A8xx14FF…`) |
| 5 | DISP `0xFFF4` | **15–17** | 616 | **Not protobuf** — UI struct / `63FA…` family |
| 6 | NZC `0xCD` `0xFFF4` | **15** | 2 | **Not protobuf** — per-nozzle proprietary |

**Mode family map (spray vs transport):**

| Spray (boom active) | Transport (road) |
| :--- | :--- |
| `F43401` + `F10E4C` or `F10E5C` | **`F43400` + `F10E1C` + `F22500`** |
| MNC suffix **`110200`** dominant | MNC suffix **`110100`** dominant |
| `4F1401`/`4F3601` flow churn ~1 Hz | `4F1401` static (`0000`) |

**Next hunt target:** SA **`0xBA`** if Diagnostics names it; otherwise deprioritize CAN protobuf — nanopb likely on ECU Ethernet/MQTT path per `JD_THIRD_PARTY_SOFTWARE.md`.

---

## Open decode queue (priority)

1. ~~**SRC `4F0B06` section map**~~ — **done** (`section_map.json`, 2026-06-11).
2. ~~**MNC CB00 lane grammar**~~ — **structure done** (`mnc_cb00_map.json`, 2026-06-12); per-nozzle + JD_SEC diff remain.
3. ~~**SRC EF00 prefix catalog**~~ — **69% classified** (`src_ef00_catalog.json`); **`F70400` idle** remains; **`F43400`/`F10E1C`/`F22500` transport trio tagged** (2026-06-15).
4. **JD_SEC `0xF7` CB00** vs MNC timing diff.
5. **NZC `0xFFF4`** — nozzle feedback linkage.
6. **SA `0xBA` / `0xD5`** — Diagnostics Center name.
7. **DISP `0xE600`** — classify VT noise vs spray side channel.
8. **GWC `0x94`** — confirm absent on X119-only tap.

---

## Promotion checklist (unknown → catalog)

When a `(controller, PGN)` pair is understood:

- [ ] Add row to **Decoded elements** in this file with `confirmed` / `likely` status
- [ ] Add or update entry in `spray_pgn_library.py` `PGN_CATALOG`
- [ ] Run `export_library_json()` or `compile_pgn_catalog.py` to refresh JSON
- [ ] Add analyzer helper under `scripts/` if timeline extraction is repetitive
- [ ] Update `JD_ISOBUS_MAP.md` only for **architecture / safety** decisions — keep field byte decodes here

---

## Related files

| File | Role |
| :--- | :--- |
| `library/spray_pgn_library.json` | Recorder + bench-ui filter |
| `library/field_observations.json` | Auto-merged session statistics |
| `sniff_616r.py` | SA labels + 616R roster |
| `scripts/decode_gps_track.py` | GPS track CSV + GeoJSON from `frames.csv` (ATX FEF3/FEE8, FEF1 speed) |
| `scripts/decode_src_ef00.py` | SRC EF00 rate / pressure timeline |
| `scripts/compile_pgn_catalog.py` | Regenerate field observations |
| `scripts/analyze_616r_session.py` | Post-session report |
| `scripts/analyze_op_notes.py` | Operator-window vs shadow + MNC CB00 correlation |
| `scripts/analyze_section_cascade.py` | Section-toggle sessions: MNC prefixes + SRC `4F0B06` |
| `scripts/build_section_map.py` | Print section map table from single-toggle sessions |
| `scripts/diff_section_capture.py` | Quick per-session FF/bitmap summary |
| `library/section_map.json` | Machine-readable R5–L5 SRC EF00 map |
| `library/PROTOBUF_HUNT_CHECKLIST.md` | Step-by-step nanopb/protobuf candidate workflow |
| `scripts/probe_protobuf.py` | Wire-tag scorer for unknown payloads (no .proto required) |
| `library/mnc_cb00_map.json` | MNC CB00 lane + suffix families |
| `library/src_ef00_catalog.json` | SRC EF00 element prefix catalog |
| `library/bus_roster.json` | SA roster + unknown nodes |
| `library/disp_catalog.json` | DISP 0xF0/0x26 prefix catalog |
| `library/mnc_event_slowdown_20260615.json` | MNC ASC suffix at headland/slowdown |
| `library/mnc_tail_spray_live_asc.json` | MNC CB00 tail4 vs speed windows (+120–250 s) |
| `library/protobuf_hunt_spray_live.txt` | Full priority-queue probe output |
| `scripts/analyze_mnc_tail_window.py` | MNC bytes 4–7 vs FEF1 speed by time window |
| `scripts/decode_disp.py` | DISP + optional MNC window analysis |
| `JD_ISOBUS_MAP.md` | Architecture, avoid-set, pathway decisions |
