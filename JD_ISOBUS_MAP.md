# PUFVision ISOBUS Integration & John Deere Address Map Specification

This document serves as the authoritative, single source-of-truth reference and technical specification for integrating the **PUFVision** machine vision engine as an independent real-time rate provider and telemetry node on John Deere machinery (such as the John Deere 616R sprayer equipped with ExactApply).

---

## 1. Overall Strategy & Integration Philosophy

### 1.1 Coexistence Goal
Create an independent, sensor-based real-time rate / prescription source that seamlessly commands application rates to the host tractor, avoiding address and functional conflicts on standard J1939 and ISOBUS networks.

### 1.2 Core Integration Principles
- **No Direct Valve Control**: PUFVision does *not* actuate sections or valve hardware directly on standard rate-controlled runs. 
- **Delegated Actuation**: Let the John Deere Rate Controller + ExactApply handles nozzle commands, section control, and official EPA-compliant operations documentation.
- **Isolate Roles**: PUFVision operates either as a high-speed variable rate prescription provider (via Task Controller Geo-referenced messages or the custom PGN 160 bypass) or as an informational monitor, maintaining its own parallel logging system for high-resolution agronomic analysis.
- **Minimal Conflict footprint**: Avoid full and complex AEF TC-SC (Section Control) server emulation at this stage to prevent fighting display-internal section control state machines.

---

## 2. Controller Role & CAN Safety Rules

### 2.1 Role Boundaries

| Correct Role / Action | Incorrect Role / Action | Technical Justification |
| :--- | :--- | :--- |
| **Independent Rate Provider** | Working Set Master | Avoids index/identification collisions and virtual terminal conflicts. |
| **TC-GEO / Custom Rate Broadcasting** | Direct Section Switching | Prevents high-speed valve command oscillation on primary CAN buses. |
| **Parallel High-Resolution Logger** | Exclusive Job System of Record | Bypasses display telemetry limitations; preserves raw sensor weed metrics. |

### 2.2 Safety & Conflict-Avoidance Rules
1. **Control Authority Ladder Enforcement (engine-enforced)**: All transmission is gated by an explicit, staged **Control Authority** state machine (see §9). The system **boots in `OBSERVE`** (pure silent sniffer, zero TX) and cannot transmit rate or section commands until the operator deliberately raises the rung *and* arms actuation. This replaces the older "always passive" claim, which was documentation-only and **not** enforced in code — `engine.py` now hard-gates every TX path through `_tx_allowed()`.
2. **Standard Non-Intrusive Handshakes First**: Address Claiming, Working Set Maintenance, TC client announce and the VT handshake are only emitted at `ANNOUNCE` and above. `OBSERVE` writes nothing to the bus at all.
3. **Never Spoof or Override Safe Limits**: Apply strict minimum/maximum rate thresholds within the vision engine.
4. **Dynamic Interlocks (engine-enforced)**: A tripped interlock force-safes the outputs (rate → 0, sections → closed) rather than holding the last value. Speed ≤ `min_ground_speed_kmh` (0.5) is treated as *normal stop* (force-safe, no demote). Loss of bus RX or the UI heartbeat is treated as a *fault* and auto-demotes to `SHADOW` (see §9.2).
5. **No Direct SECTION Valve On/Off Command Until `SECTION` Rung**: Section bitmaps are only transmitted at the `SECTION`/`FULL` rungs while armed, and on cooperative profiles are AND-gated against the host's commanded sections so PUFVision can only ever *subtract* coverage, never add it where the host has closed.
6. **Physical Line Separation**: Ensure the hardware bus adapter's internal 120Ω termination resistance is configured off if connecting to an already terminated diagnostic port.

---

## 3. Name, Addressing & Network Management

To comply with the ISO 11783-5 standard and ensure acceptance on John Deere CommandCenter screens, PUFVision uses a dedicated Sensor System configuration:

### 3.0 Physical Layer & Bus Speed

Two distinct electrical profiles appear in the field. PUFVision pathways map to **one** of them — do not assume a single speed across all John Deere CAN segments.

| Bus profile | Arbitration | Data phase | Frame type | PUFVision relevance |
| :--- | :---: | :---: | :--- | :--- |
| **ISO 11783 implement** (X119 / sanctioned ISOBUS connector) | **250 kbps** | 250 kbps | Classic CAN, 8-byte payload | **Goldacres GRC path** — DDI 141/157 to GRC `0xCC`. Current `engine.py` config (`bitrate=250000`, classic only). |
| **John Deere proprietary** (IB1–IB6, newer CommandCenter platforms) | **500 kbps** | **2 Mbps** | **CAN-FD**, up to 64-byte payload | **616R internal buses**, high-bandwidth implement domains. Not supported by current engine or SLCAN/COM adapters. |

**John Deere direction:** Newer JD CAN infrastructure standardises on **500 kbps arbitration / 2 Mbps data** (CAN-FD). This matches the reference material in `C:\Projects\General_files\CAN tools\Information\` (`canfddif.jpg`, `CanFD.jpg`).

**PUFVision today:** `engine.py` hardcodes classic CAN at **250 kbps** — correct for ISO 11783 and the Goldacres G5 + GRC.001 reference platform. There is no `fd=True` / `data_bitrate` path; `python-can` CAN-FD support is unused.

**Field checklist before first connect:**

1. Confirm which bus you are tapping (ISOBUS X119 vs JD proprietary diagnostic port).
2. If zero frames appear at 250 kbps, try 500 kbps classic before assuming CAN-FD — wrong speed looks like a dead bus.
3. CAN-FD segments require a native FD-capable adapter (PCAN-USB FD, Kvaser, SocketCAN+`fd`) — not the SLCAN serial path used on COM ports.
4. **616R actuation** does not depend on CAN bitrate (GreenSeeker serial, §4.3.2). CAN bitrate only affects sniff/telemetry on those machines.

> **Adapter note:** `live_decoder.py` sets USB serial to 2,000,000 baud for the host link to a Waveshare-style adapter. That is the **USB-UART speed**, not the CAN data phase. Do not confuse it with JD's 2 Mbps CAN-FD data rate.

### 3.1 Device NAME (ISO 11783 NAME Structure)

| NAME Field | Recommended Value | Notes / Technical Specs |
| :--- | :--- | :--- |
| **Device Class** | `7` (Sensor System) | Configures the system as a Vision Spray / Optical sensor array. |
| **Function** | `128` (0x80) | Identifies the controller as an independent real-time rate source. |
| **Function Instance**| `0` | Defaults to 0; incrementable if secondary devices exist. |
| **Manufacturer Code**| `1407` | Open-Agriculture designation. |
| **Identity Number**  | Unique Serial | Dedicated hardware serial identifier or static test ID. |

- **Address Claiming Profile**: Broadcast J1939 Address Claiming (PGN `0xEEFF` / 60928, Priority `6`) upon boot.
- **Preferred Address Range**: Dynamic claiming in the `128 – 247` pool (recommended default boot option is `128` or `130`).
- **Conflict Prevention**: Never use the identical NAME or Function as the sprayer's main implement control units (such as `0x82` or `0x84`).

### 3.2 See & Spray 616R Controller Roster (Field-Confirmed)

The following roster was confirmed against a John Deere **See & Spray 616R** Service ADVISOR software-update procedure (4600 CommandCenter V2). The display's **Diagnostics Center** lists every node in the authoritative format:

```
NAME.instance | 0x<SA> | <network>
```

This is the canonical way to enumerate a specific machine's live address table — read it directly off the Diagnostics Center page rather than assuming SAs. **Confirmed example: `GWC.001 | 0x94 | Implement`.** Full multi-tier CAN topology, three independent addressing schemes, and the closed vision→nozzle path are documented in **§12** (sourced from TM174719).

> **Field roster vs. service-manual roster:** §3.2 reflects live Diagnostics Center names (`SRC`, `BHC`). TM174719 uses overlapping but not identical abbreviations (`PSSC`/`SSSC`, `BH1`). The mapping table in §12.3 reconciles both.

| Abbrev. | Controller (Full Name) | Confirmed / Likely SA | Network | Role |
| :--- | :--- | :---: | :--- | :--- |
| **GWC** | Gateway Controller | **`0x94` (confirmed)** | Implement | See & Spray implement gateway / bridge. **Do not claim 0x94.** |
| **SRC** | Spray Rate Controller | `0x17` / `0xE1` (likely) | Implement | Rate + master/section command authority (supersedes "SR1"). |
| **MNC** | Manifold / Nozzle Controller | `0x68` / `0xD4` / `0x69` / `0xCD` (likely) | Implement | ExactApply nozzle actuation (supersedes "MNA"). |
| **NZC** | Nozzle Controller | TBD | Implement | Per-nozzle / segment actuation. |
| **BHC** | Boom Height Controller | `0x8A` (likely) | Implement | BoomTrac height control (supersedes "BH1"). |
| **BHS** | Boom Height Sensor | TBD | Implement | Ultrasonic / cradle height sensing node. |
| **IMU** | Inertial Measurement Unit | TBD | Implement | Boom/chassis attitude, roll/pitch for terrain comp. |
| **VPU** | Vision Processing Unit | TBD | Implement | JD's own See & Spray camera/vision processor. |

> **Naming note:** Earlier docs in this repo reference `SR1` / `MNA` / `BH1`. On the 616R these map to `SRC` / `MNC` / `BHC` respectively. The legacy abbreviations are retained in code paths for backward compatibility but the 616R roster above is authoritative for new work.

> **Diagnostic addresses ≠ J1939 SAs:** The numeric "addresses" shown inside JD's per-controller diagnostic-parameter lists (e.g. GWC params `130`, `198`) are **TLA / diagnostic parameter indices**, not J1939 source addresses. Do not confuse them with the `0x<SA>` bus address shown in the Diagnostics Center node list.

### 3.3 Section Control Timing (616R)

Confirmed turn-on / turn-off latencies for this machine, used to align frame-capture-to-fire offsets:

| Parameter | Value | Use |
| :--- | :---: | :--- |
| **Section ON delay** | `0.5 s` | Lead time to open a section ahead of target arrival. |
| **Section OFF delay** | `0.1 s` | Trailing time to close a section after target passes. |

### 3.4 Reserved Address Avoid-Set (Engine Enforcement)

The Python engine (`engine.py`, `CANController.jd_reserved_addresses`) refuses to claim any of these during dynamic address cycling, so PUFVision can never collide with a genuine JD node:

`0x94` (GWC) · `0x17`/`0xE1` (SRC) · `0x68`/`0xD4`/`0x69`/`0xCD` (MNC) · `0x8A` (BHC) · `0x1C` (ATX) · `0x26`/`0xF0` (Cab Display) · `0x00` (Engine ECU) · **`0xCC` (GRC.001)**

> **`0xCC` is mandatory:** GRC.001 (Goldacres GreenStar Rate Controller) occupies SA `0xCC` (decimal 204), which lies inside PUFVision's dynamic claim pool (`0x80`–`0xF7`). PUFVision **sends to** `0xCC` as the PDU1 destination for DDI 141/157 — it must **never claim** `0xCC` as its own source address. Without this entry, address-conflict cycling could displace the rate controller and break section/rate command paths.

### 3.5 John Deere See & Spray Vision Stack (Field-Confirmed)

From the G5 CommandCenter **Diagnostics Center**, JD's own See & Spray vision system is a **two-tier** architecture. Understanding it matters because the CAN-facing tier *self-configures addresses in the same 128–247 pool PUFVision claims in* — our collision-cycle + avoid-set must coexist with it.

**Tier 1 — Vision Spray 2.0 CAN modules (the VPUs, on the Implement network):**

| Device | ISO NAME (hex) | Function Instance | Role |
| :--- | :--- | :---: | :--- |
| `VP1.001` | `A022810004200000` | 0 | Vision Spray module 1 |
| `VP2.002` | `A022810804200000` | 1 | Vision Spray module 2 |
| `VPL.006` | `A022812804200000` | 5 | **Lead** Vision Spray module |
| `VPA.010` | `A022814804200000`* | 9 | Vision Spray module "A" |

*\*VPA NAME reconstructed from the decoded field pattern; instances 0/1/5/9 confirmed on-screen.*

Decoded common NAME fields (all VP modules):

| NAME field | Value |
| :--- | :--- |
| Self-Configurable Address | **Yes** (dynamic claim) |
| Industry Group | `2` (Agricultural & Forestry) |
| Device Class | `17` (display labels it **"Sensor System"**) |
| Device Class Instance | `0` |
| Function | **`129` (0x81)** |
| Manufacturer Code | **`33` (John Deere)** |
| ECU Instance | `0` |
| Diagnostic Protocol | `J1939-73` |

**Tier 2 — Image Processors (NOT on CAN):** Ethernet-connected camera processors (e.g. `172.16.0.190`, 4 camera ports each, HW `PFA12759`, SW `PFP25981 v7.00.0031`, ~14.6 V). Pipeline: **Cameras → Image Processors (Ethernet) → Vision Spray modules (CAN) → sprayer.** PUFVision never sees Tier 2 on the bus.

> **PUFVision NAME guidance:** Do **not** mimic the JD vision NAME (`Function 129`, `Manufacturer 33`) — that invites identity conflict with a genuine node. Keep PUFVision distinct: `Function 128 (0x80)`, `Manufacturer 1407 (Open-Ag)`, `Device Class 7 (Sensor System)`, `Identity 1234`. (The engine's `name_payload` is maintained to encode exactly these fields.)

### 3.6 ISOBUS Documentation Mode & Task Totals

From the display Help Center: **ISOBUS Documentation Mode must be ON to record ISOBUS task totals.** Totals exchange is either:
- **Controlled by Display (recommended):** display polls the implement for totals at frequent intervals, or
- **Controlled by Implement:** implement pushes totals on its own (less frequent) schedule.

Relevant only if/when PUFVision's as-applied data is to be reconciled into JD job documentation; not required for the GoB GreenSeeker rate path.

---

## 4. Key Messaging Pathways

PUFVision uses two distinct messaging pathways to feed target application demands to the sprayer system:

### 4.1 Pathway A: Standard Task Controller Geo-Referenced (TC-GEO)
- **Message Type**: Standard ISO 11783-10 Process Data PGN `57344` (`0xE000`)
- **Variables mapped**: Target variable-rate application commands via DDI `0x004F`.
- **Target Use Case**: Standard compliant rate-injection where the display handles standard variable-rate prescriptions.

### 4.2 Pathway B: John Deere Custom Bypass Channel (PGN 160)
- **Message Type**: Proprietary J1939 Process Data PGN `160` (`0x00A0`), utilizing PDU1 format (PF: `0xA0`, Destination: Destination-Specific Address).
- **Target Device**: John Deere GreenStar Rate Controller (GRC.001) with fallback/default Source Address **`0xCC`** (decimal 204) on the implement network.
- **Justification**: Standard TC-GEO messages can experience latency or filtering on older John Deere Gen 4 (4600) CommandCenter systems.
- **Target Entities**: Maps two private Data Dictionary Entities (DDIs) for direct sensor-to-controller exchange:

| Entity DDI | Hex Value | Direction | Functionality |
| :--- | :--- | :--- | :--- |
| **DDI 157** | `0x009D` (LE: `0x9D 0x00`) | **PUFVision → John Deere** | Transmits raw real-time target weed density index or scaled dynamic variable rate. |
| **DDI 158** | `0x009E` (LE: `0x9E 0x00`) | **John Deere → PUFVision** | Receives actual applied nozzle-flow feedback from JD Rate Controller to close the loop. |

### 4.3 Pathway G: GreenSeeker Serial Prescription (RS232 COM Port 2) — *Primary GoB path*

This is the **lowest-risk, highest-confidence** route for the 616R: the GreenStar display ships a sanctioned, fixed serial parser for a Trimble/JD **GreenSeeker** optical sensor. PUFVision emulates the GreenSeeker "control unit" over RS232, feeding a vision-derived target rate in as a *native prescription* without ever writing to John Deere's protected CAN.

**Confirmed from a live G5 CommandCenter "COM Port Diagnostics" page (COM Port 2):**

| Diagnostic Field | Expected Value / Behaviour | PUFVision obligation |
| :--- | :--- | :--- |
| **Device Type** | `N-Sensing` | We must present as an N-Sensing source. |
| **Manufacturer** | `GreenSeeker` | Identity expected by the parser. |
| **RC Message** | Goes **Active** when the display receives our stream | Our keepalive sentence — *"required from the GreenSeeker control unit for proper operation."* |
| **Target Rate Dry** | Granular target rate | Display ingests a **finished rate**, not raw NDVI. |
| **Target Rate Wet** | Liquid target rate | Liquid channel (Clare Downs = wet). |
| **Last Message Received** | Timestamp / staleness | Drives the display's link-health watchdog. |

> **Key implication:** The display wants a **computed target rate** (dry/wet), *not* raw NDVI. The NDVI→rate crop-algorithm math that historically lived in Trimble's *RT Commander* PDA software is therefore **PUFVision's responsibility**; we emit the finished rate.

**Display serial role map (from the COM Port Settings help page):**

| Port | Source | Required message |
| :--- | :--- | :--- |
| **COM 1** | Field Doc Connect | `AR Message` |
| **COM 2** | GreenSeeker | `RC Message` |
| **COM 2** | Nitrogen sensor | `D2 Message` |
| Serial GPS | NMEA receiver | Speed + position/velocity/time |

**Confirmed GreenSeeker RT200 link layer** (Trimble *RT200 System Installation & Operation Guide*, "Data output"):

| Parameter | Value |
| :--- | :--- |
| Transport | RS-232, **38400 baud, 8 data, No parity, 1 stop** (`38400-8N1`) |
| Framing | ASCII text, **one line per sample** |
| Payload per line | **NDVI value + a second user-selected VI value** |
| Default Selected V.I. | `NDVI` |
| Data Format (RT200 setup) | Must be **`RT200`** for live VRA (other formats are simulation-only) |
| Update cadence | **1 Hz = 495 ms**, 2 Hz = 245 ms, 5 Hz = 200 ms |
| GPS feed | NMEA-0183, `GGA`+`VTG` or `GGA`+`RMC`, ~4800 baud |
| Legacy rate-controller link | e.g. Raven @ 9600 baud (RT Commander → controller) |

**Open item (pending serial capture):** the exact byte/field framing of the GreenSeeker **"RC Message"** target-rate sentence. The transport and ingest contract above are confirmed; only the sentence layout is unverified. In code this is isolated to a single `GreenSeekerProtocol` subclass — see `python/greenseeker_emitter.py` (`RT200Protocol` stub + `GenericNdviProtocol` placeholder). No other code changes are needed once the frame is captured.

**Implementation status:** `GreenSeekerEmitter` (background 1 Hz, pyserial, `38400-8N1`) with speed interlock and dry/wet rate channels is wired into `engine.py`; IPC commands `SET_GS_EMITTER`, `SET_GS_COM_PORT`, `SET_GS_BAUD`, `SET_GS_PROTOCOL`; live status surfaced in the ISOBUS UI "GreenSeeker Serial Link" panel.

#### 4.3.1 Pathway E: Whole-Boom Blanking ("section-like" GoB spot spray via the rate channel)

The 616R's See & Spray vision stack owns per-section/per-nozzle control behind a closed Ethernet/CAN system, so true section on/off is not reachable through the serial path. The fail-safe approximation is **whole-boom blanking**: modulate the *single* GreenSeeker rate channel between the target rate (boom sees weeds) and **0 L/ha** (clean ground).

- **Detection signal**: `CANController.vision_weeds_present()` — true when the camera sees a sprayable target anywhere across the boom (GoB: any detection; GoG: an identified "Target"). Works with **no CAN attached** (serial-only on the 616R).
- **Anti-chatter / coverage**: a trailing **spray hold** (`blank_hold_s`, default 0.7 s) keeps the rate up briefly after the last detection so the boom doesn't flicker and weeds get overlap.
- **Fail-safe by construction**: a false "clean" reading only *under-sprays* (the weed is caught next pass); the path can never *add* application over clean ground. A provider/exception failure defaults to **spraying** (never silently blanks).
- **Interlocks**: the existing speed interlock still forces rate 0 when stopped; the min-rate floor is dropped to 0 only while blanked.
- **Implementation**: `GreenSeekerEmitter.boom_blanking` + `set_boom_blanking()` / `set_blank_params()`; IPC `SET_GS_BLANKING`, `SET_GS_BLANK_HOLD`, `SET_GS_BLANK_RATE`; telemetry `gs_boom_blanking` / `gs_blank_state` (`off|spraying|blanked`); UI toggle + hold-time + live SPRAYING/BLANKED indicator in the GreenSeeker Serial Link panel.
- **Limitation**: it is **whole-boom**, not per-section — the entire boom blanks or sprays together. Per-section spot on the 616R remains gated behind JD's closed vision stack (see **§12.6–§12.7** for the Camera→FAKRA→VPU→NZC path PUFVision cannot enter); for true multi-section GoB use the Goldacres native-CAN path (§10.1) or a standalone section driver (§11.4).

#### 4.3.2 Settled 616R Path — GreenSeeker Whole-Boom Only (Decision Closed)

**Status:** *Approved — do not relitigate CAN section injection or See & Spray emulation on the 616R unless JD exposes a new cooperative implement interface.*

The 616R field program runs **Pathway G** (GreenSeeker serial rate prescription) plus **Pathway E** (whole-boom blanking). No other live GoB actuation path is planned for this machine.

**Why implement-driven section control is not reachable**

ISO 11783-10 assigns **section on/off authority to the Task Controller server** (the display), not to a third-party implement node. The implement describes sections in its DDOP, reports *actual* condensed work state, and executes *setpoint* condensed work state from the TC. To command JD sprayer sections from outside, PUFVision would need to occupy one of two roles:

| Required role | 616R reality |
| :--- | :--- |
| **TC server** (section setpoint originator) | Gen 4 CommandCenter owns this; not substitutable without full TC server emulation |
| **Open implement rate/section controller** (process-data listener) | No equivalent — sprayer implement **is** the integrated PSSC/MNC/VPU See & Spray stack (§12.3, §12.6) |

There is no third-party slot on the 616R for an external node to drive section bitmaps the way a Goldacres GRC.001 accepts DDI 141 at `0xCC` (§10.1).

**Why legacy open-controller paths do not apply**

Legacy systems that accept external section/rate commands — GreenStar Rate Controller (liquid), Raven, TeeJet, KZCO, Banjo via 3-wire section valves — work because an **open implement controller** sits on an **open implement bus** and listens for process data. The 616R does not expose such a controller; its spray authority is the closed See & Spray / ExactApply system. The command concept (section bitmap, rate setpoint) is the same; the **socket to plug into does not exist**.

**Paths explicitly ruled out for 616R live GoB**

| Path | Ruling |
| :--- | :--- |
| **Pathway D** — VPU / implement-bus emulation | Architecturally invalid (§12.6–§12.7); MNC NZC addressing, GWC handshake, FAKRA ingest |
| **CAN section interceptor** ("drafting gate", §14) | Poor fit on IB1 (GWC/SRC rebound); impossible on IB3–IB6 without MNC emulation |
| **TC-GEO prescription map** (DDI `0x004F`, Pathway A) | JD honours *pre-loaded* zero-rate zones — **not** real-time vision. Viable only as a two-pass workflow (map weeds → spray prescription), which forfeits single-pass GoB economics |

**The one sanctioned real-time external input**

GreenSeeker on **COM Port 2** is the only live sensor rate channel John Deere designed the display to ingest without entering the closed CAN stack (§4.3). Pathway E turns that single channel into boom-granular GoB by modulating rate between target L/ha and **0** over clean ground (§4.3.1).

**ROI dependency (Clare Downs)**

Whole-boom blanking savings depend on **weed patch distribution**:

- **Patchy / clustered weeds** — boom spends meaningful time fully blanked between patches → strong chemical savings.
- **Sparse but evenly scattered weeds** — boom rarely sees a fully clean width → blanking triggers seldom → savings approach zero; per-section resolution forgone on the 616R may matter more in this regime.

Validate patchiness on target country before treating Pathway E as sufficient ROI; if weeds are too scattered, prioritize Goldacres per-section trials (§10.1).

**Cross-references:** closed vision path §12.6; implications table §12.7; likelihood §10.2; interceptor brainstorm §14.8 (616R deferred).

#### 4.3.3 AEF TC Server on the 4600 — What Certification Does and Does Not Unlock

The Gen 4 CommandCenter (4600) is **AEF ISOBUS-certified as a Task Controller server**, typically bearing **TC-BAS**, **TC-GEO**, and **TC-SC** (not TC-BAS alone). Do not conflate *"display is certified"* with *"PUFVision can drive 616R sections."*

**AEF role model (ISO 11783-10)**

| Functionality | Server (4600 display) | Client (implement ECU) |
| :--- | :--- | :--- |
| **TC-BAS** | Task totals, as-applied documentation, ISO-XML export to FMIS / Operations Center | Reports process data; mandatory baseline when TC-GEO or TC-SC is implemented |
| **TC-GEO** | Geo-referenced prescriptions; sends rate setpoints by position | Uploads DDOP; executes/reports setpoint and actual rate DDIs |
| **TC-SC** | Boundary/headland section logic; sends *setpoint* condensed work state | Uploads DDOP with section geometry; executes valves; reports *actual* work state |

Section authority remains with the **TC server**. The implement **executes** setpoints — it does not independently command the display's section state machine.

**What PUFVision does today**

- Declares TC client capabilities (`0x07` = TC-SC + TC-GEO + TC-BASIC) in the 1 Hz `0xCB00` announce (`engine.py`).
- Uploads a **VT object pool** (ISO 11783-6) only — **not** a Task Controller **DDOP** (ISO 11783-10).
- No ISO-TP DDOP transfer, no TC pairing state machine, no handling of setpoint condensed work state from the display.
- Goldacres bypasses pairing with direct DDI 141 to GRC `0xCC`; 616R actuation uses GreenSeeker serial (§4.3.2).

**Does not unlock (616R sections)**

AEF TC-SC **server** certification means the 4600 will interoperate with any AEF-certified **implement TC client** that uploads a conformant DDOP. On the 616R, nozzle actuation lives in the closed PSSC/MNC/VPU/NZC stack (§12) — not on an open ISOBUS TC client at `X119`. Making PUFVision a certified TC client on the ISO bus would register PUFVision *as* the implement to the display; it would not command ExactApply nozzles. **§4.3.2 decision stands.**

**Does unlock (research track)**

| Opportunity | Platform | Notes |
| :--- | :--- | :--- |
| **TC-GEO rate via proper TC Client** | 616R ISO connector | Alternative to PGN 160 bypass or GreenSeeker serial if Work Setup authorises paired client; untested |
| **Official TC-SC pairing** | Goldacres | DDOP-driven pairing may be more stable long-term than raw DDI 141 bypass |
| **TC-BAS / ISO-XML task export** | Both | Certified as-applied path into MyJohnDeere / Operations Center; complements `myops_telemetry.csv` (§7.2) |
| **As-applied reporter only** | Both | TC-GEO allows clients *without controllable elements* that report process data for mapping |

**Concrete check before building:** query the [AEF ISOBUS Database](https://www.aef-isobus-database.org/) for the **4600 + 616R sprayer combination** — confirms which TC functionalities the *pair* supports and whether the sprayer exposes an ISOBUS TC client at all. If the sprayer is not listed as a TC-SC client, display certification is irrelevant to boom sections.

**Cross-references:** TC client announce §9; Pathway A (TC-GEO) §4.1; DDOP gap noted in `engine.py` (`SET_SPRAYER_PROFILE` comments); Ops Center CSV sketch §14.7.

---

## 5. Low-Level Address Map

Based on Diagnostic Technical Specifications of John Deere control modules (SR1, SR2, MNA, ATX, BH1), the following indices are monitored or injected on the CAN / ISOBUS network:

### 5.1 Operator Controls (SR1 / Read Only)

| Controller | Address Index | Parameter | Value Representation | Intended Purpose |
| :--- | :---: | :--- | :--- | :--- |
| **SR1** | `23` | Master On/Off Auto Button State | `0` = Inactive / `1` = Active | Evaluated as a hardware interlock allowing vision triggers. |
| **SR1** | `20` | Manual Spray Switch | `0` = Open / `1` = Closed | Manual test trigger or override. |

### 5.2 Boom & Sprayer Physical Geometry (SR1 / Read Only)

| Controller | Address Index | Parameter | Range / Metrics | Intended Purpose |
| :--- | :---: | :--- | :--- | :--- |
| **SR1** | `166` | Number of Boom Sections | `5 — 15` count | Configures internal mapping partitions of camera grids. |
| **SR1** | `167` | Physical Boom Width | `80 — 150` ft | Scales translation speed based on camera overlap calculations. |
| **SR1** | `172` | Individual Nozzle Control Enable | `0` = Generic / `1` = Installed | Switches system between Section-level and Nozzle-by-Nozzle modes. |

### 5.3 Section & Nozzle Actuation Monitoring (SR1 & MNA / Write & Read)

| Controller | Address Index | Parameter | Range / Code | Intended Purpose |
| :--- | :---: | :--- | :--- | :--- |
| **SR1** | `31` | Section Valve Command Status | Bits L7 to R7 On/Off | Monitors the physical section open/close directives. |
| **SR1** | `30` | Section Feedback Status | Bits L7 to R7 State | Confirms that physical solenoid valves have completed movement. |
| **MNA** | `104–107` | Subnet Nozzle Counts | `1 — 128` per group | Indexes unique nozzle sequences for ExactApply. |

### 5.4 Steering, Velocity, & GPS Navigation

| PGN / Source | Parameter Name | Scope | Resolution | Intended Purpose |
| :--- | :--- | :--- | :--- | :--- |
| **PGN 65256** | Navigation Wheel-Based Speed | J1939 Standard | Velocity km/h | **CRITICAL**: Controls delay offsets between frame capture and solenoid fire. |
| **PGN 129026**| SOG / COG Rapid Update | J1939 Standard | GPS Heading & Speed | Secondary speed reference used if wheel slip is detected. |
| **PGN 65267** | GPS Position Coordinates | Lat / Lon | Under degrees | Geo-marks coordinates of weed detections. |
| **PGN 61481** | Gyro Yaw Rate / Lat Accel | J1939 Standard | Rad/s | Compiles inner vs. outer sweep velocities during boom turns. |
| **ATX 1025** | Wheel Angle Curvature | John Deere ATX | deg/m | Compensates for camera parallax offset on curves. |

### 5.5 Height Controls (BH1 / Monitor)

| Controller | Address Index | Parameter | Range Values | Intended Purpose |
| :--- | :---: | :--- | :--- | :--- |
| **BH1** | `23` | BoomTrac™ System Active Button | `0` = Off / `1` = Engaged | Monitors if auto height control is maintaining boom stability. |
| **BH1** | `133` | Center Frame Target Height | `0 — 100` % | Used to estimate camera FOV width scale factor. |
| **BH1** | `134` | Left Wing Target Height | `0 — 100` % | Evaluates side wing offset height calibration. |
| **BH1** | `135` | Right Wing Target Height | `0 — 100` % | Evaluates side wing offset height calibration. |

### 5.6 Boom Position Validations & Failsafes (BH1 / Safety Safeguard)

| Controller | Address Index | Parameter | Fail Condition | Failsafe Action |
| :--- | :---: | :--- | :--- | :--- |
| **BH1** | `10–17` | Wing Folded Sensor State | Fold Level `> 5%` | Halts vision processing for folded boom sections immediately. |
| **BH1** | `114` | Transport Physical Road Lock | Status == `1` | Global hardware lock; keeps solenoids strictly closed in transit. |
| **BH1** | `108–109` | Wing Cradle Ultrasonic Level tilt | Out of safe bounds | Disables spraying for sections displaying unstable wing tilt. |

### 5.7 ExactApply Subnet Topology Mapping (MNA / Read Only)

| Controller | Address Index | Parameter | Range Values | Intended Purpose |
| :--- | :---: | :--- | :--- | :--- |
| **MNA** | `112` | Active Nozzle CAN Subnets | `1 — 4` lines | Maps physical layout boundaries of ExactApply. |
| **MNA** | `108–111` | Subnet Installation Order | L-to-R vs. R-to-L | Matches right/left camera feeds with physical nozzle IDs. |
| **MNA** | `126` | Valve Block Plug Sensors | Boolean indicator | Flags failure if target flow states are not delivered. |

### 5.8 Sprayer Fluid Safeguard Values (SR1 / Read Only)

| Controller | Address Index | Parameter | Operational Limit | Action on Flag |
| :--- | :---: | :--- | :--- | :--- |
| **SR1** | `8` | Pipe Solution Jet Pressure | Below `15` psi | Triggers "Low Pressure / Empty Line" warning on dashboard UI. |
| **SR1** | `26` | Solution Liquid Tank Volume | Volume Level `< 10` gal | Pauses vision-rate requests to prevent nozzle element damage. |
| **SR1** | `14 / 16` | Flow Meter Feedback | No movement on spray | Signals system failure if fluid does not dispense when requested. |

---

## 6. John Deere CommandCenter Setup & Calibration

To enable rate command injection using the PUFVision address-map logic, verify the following configurations in the **John Deere Gen 4 (4600 / 4200) CommandCenter**:

1. **Enable ISOBUS Network Access**: Ensure the ISOBUS network switch under diagnostics is checked "Active".
2. **Authorize Task Controller**: Navigate to *Work Setup* and set *Task Controller (TC)* and *Variable-Rate Application (VRA)* permissions to "Active".
3. **Select Rate Source**: In the *Work Setup* layout, configure the application rate controller's input source to feed from the **PUFVision Optical Sensor** (or corresponding Sensor Class ID claim).
4. **Command Cycle Trigger**: When modifying NAME structures or claim ranges on the bus, cycle the tractor's master auxiliary run keys to clear stored display controller tables.

---

## 7. Logging & Loop Closure

### 7.1 Closure Loop Tracking
The system establishes a closed loop in real-time by linking requested rates directly to active feedback.

```
+--------------------+   PGN 160 DDI 157   +--------------------------+
|  PUFVision Sensor  | ------------------> | John Deere Gen 4 Display |
| (Calculated Rate)  |                     |  & Sprayer controller    |
+--------------------+                     +--------------------------+
          ^                                              |
          |                                              |
          |           PGN 160 DDI 158 Feedback           v
          +----------------------------------------------+
```

### 7.2 MyOps Telemetry CSV File Specification
All rate entries, feedback loop statuses, and raw sensor readings are written at a high frequency of **20Hz** to `myops_telemetry.csv`:

```
timestamp,greenness_index,target_rate_l_ha,actual_flow_rate_l_min,speed_kmh,section_bitmap,jd_commanded_sections,jd_headland_active,ddi_157_val,ddi_158_val
```

---

## 8. Phased Development Implementation Plan

1. **Phase 1: Bus Entry & Address Claim Verification**
   Isolate correct sensor category NAME claims; verify visible registration on the J1939/ISOBUS active devices directory.
2. **Phase 2: Handshake & Fixed-Rate Exchange**
   Transmit stable, static test variable-rates (e.g., 40.0 L/ha) to verify John Deere CommandCenter compatibility and registration.
3. **Phase 3: Sensor-Derived Speed & Rate Command loop**
   Link camera greenness metrics directly to dynamic rate calculation limits, transmitting corresponding commands over the network.
4. **Phase 4: Feedback Loop Resolution & Automated Logging**
   Capture live flow feedback metrics (from standard TC feedback or the DDI 158 bypass), mapping variables directly inside independent files.
5. **Phase 5: Diagnostics UI Integration**
   Load interactive diagnostic visualizers and calibration setups on the Virtual Terminal to allow on-screen adjustments by the operator in the cab.

---

## 9. Control Authority Ladder & Safe Online Staging

The single biggest risk in bringing CAN injection online is jumping straight from "monitoring" to "actuating" on a live machine. To remove that risk, transmission authority is staged on an explicit ladder that is enforced in `engine.py` (not just documented). Every rung only permits what the rung below allows **plus** its own new category, and nothing actuates without a deliberate `ARM`.

### 9.1 The Ladder

| Rung | Name | What it transmits | Arming | Purpose / exit criteria before climbing |
| :--: | :--- | :--- | :--- | :--- |
| 0 | **OBSERVE** | *Nothing* — pure sniffer | n/a (boot default) | Confirm zero TX in the sniffer; decode the host roster & PGNs. |
| 1 | **ANNOUNCE** | Address Claim, WSM, TC client announce, VT handshake | n/a | Confirm PUFVision appears in the display's device list with the correct NAME and a non-colliding SA. |
| 2 | **SHADOW** | *Still nothing actuating* — full pipeline computes + logs rate & section bitmap with TX suppressed | n/a | Compare PUFVision's intended rate/sections against the host's live behaviour offline. This is the key validation rung. |
| 3 | **RATE_ONLY** | DDI 157 rate (PGN 160) | **ARM required** | Verify the display accepts our rate as a source and the value tracks vision. Sections remain the operator's/host's. |
| 4 | **SECTION** | Section bitmap (AND-gated) **+** rate | **ARM required** | Whole-section spot control validated on the bench/virtual bus, then native CAN (Goldacres) first. |
| 5 | **FULL** | Rate + sections, all interlocks live | **ARM required** | Production operation. |

- **IPC**: `SET_CONTROL_AUTHORITY:<RUNG>`, `ARM`, `DISARM`, `UI_HEARTBEAT`, `SET_SPEED_INTERLOCK:<0|1>`.
- **Telemetry**: `control_authority`, `control_armed`, `control_interlocks{speed,rx,ui}`, `control_demote_reason`, `section_bitmap`.
- **UI**: the ISOBUS tab's **Control Authority** card renders the ladder, interlock LEDs, an ARMED/SAFE indicator and a `confirm()` gate on every actuation-capable rung. Arming is refused below `RATE_ONLY`. Dropping below `RATE_ONLY` auto-disarms.
- **Gate implementation**: `_tx_allowed(kind)` where `kind ∈ {claim, presence, rate, section}` is the single source of truth; `claim`/`presence` need `≥ ANNOUNCE`, `rate` needs `armed && ≥ RATE_ONLY`, `section` needs `armed && ≥ SECTION`.

### 9.2 Interlocks & Watchdogs

| Interlock | Trip condition | Response | Demotes authority? |
| :--- | :--- | :--- | :--- |
| **Speed** | ground speed `< 0.5 km/h` | Force-safe: rate → 0, sections → closed | **No** (normal stop — resumes when moving) |
| **Bus RX** | no CAN RX for `> 2.0 s` while a bus is attached | Force-safe + auto-demote to `SHADOW` | **Yes** (genuine fault) |
| **UI link** | no `UI_HEARTBEAT` for `> 3.0 s` | Force-safe + auto-demote to `SHADOW` | **Yes** (renderer freeze/crash) |

The UI heartbeat is emitted at 1 Hz from the always-mounted React root (`App.tsx`), so a tab change does **not** trip it — only a true UI freeze/crash does. The watchdog runs every engine tick (`_service_watchdogs`).

### 9.3 Engine-Side Section Trigger (UI-independent control loop)

The weed → section decision was moved out of the renderer and into the engine (`CANController.update_vision_sections`, called at 10 Hz):

- Camera publishes `frame_w`; each cached detection box maps by horizontal centre into `num_boom_sections` (default 10) columns across the boom. On Goldacres, this count must match GRC *Work Setup* section geometry (§10.1), not the default.
- A per-section `section_hold_time` (default 0.5 s) keeps a section ON briefly after the last hit for trailing coverage.
- The resulting `section_bitmap` is then AND-gated against `jd_commanded_sections` on cooperative profiles before any (gated) transmission.
- Manual `NOZZLE_CMD` is ignored while `engine_side_sections` is true — single source of truth, no UI round-trip latency.

### 9.4 Recommended Bring-Up Order

`OBSERVE` → `ANNOUNCE` → `SHADOW` (validate against live host) → `RATE_ONLY` + ARM (bench/virtual) → `SECTION`/`FULL` + ARM (Goldacres native CAN first). Each rung is independently testable on the virtual bus before any real adapter is attached.

---

## 10. Likelihood of Success & End Capabilities

### 10.1 Goldacres (native ISOBUS / GRC.001) — **High (~75–85%)**

- **Path**: PUFVision claims an address, announces as a TC client, and injects DDI 141 section state + DDI 157 rate directly to the GRC.001. The Goldacres G5 Universal stack is comparatively open and listens for process data from any valid address-claimed node.
- **End capability**: whole-section Green-on-Brown spot spray **with variable rate**, cooperatively AND-gated with the host so PUFVision can only close sections the host left open.
- **Main risks**: TC-SC authorization handshake nuances, section command cadence/oscillation tuning, confirming DDI 141 element addressing on the specific GRC firmware.
- **Field bring-up (liquid GRC, OMPFP10673 operator manual):** Before section-blanking GoB trials, set **Minimum Flow Rate = 0** in G5 *Work Setup*. The GRC maintains a minimum-flow floor even when all sections are commanded OFF; at ground speeds below the engine speed interlock (`0.5 km/h`, §9.2) this produces measurable over-application on closed sections. Section blanking on the `goldacres_grc` profile (DDI 141 only — rate held by GRC, see §4.2 and engine `PROFILE_GOLDACRES_GRC`) therefore depends on the operator zeroing that floor first.
- **Section geometry:** Map the vision section bitmap to the **configured section count and widths** from GRC *Work Setup*, not the engine default `num_boom_sections = 10` (§9.3). A typical Goldacres 3-wire Raven boom supports up to **10 sections**, but the active count may be fewer — bit positions must align to the display's section indexing (center-outward C / L1–L5 / R1–R5). Hardcoding ten equal camera columns mis-aims spot spray when fewer sections are configured. On cooperative profiles the bitmap is still AND-gated against `jd_commanded_sections` (§9.1) before any `SECTION`-rung TX.

#### 10.1.1 GRC Section Bitmask, EF00 Elements & DDI 141 Command Path

Field-validated on Goldacres G5 + GRC.001 (`gatest_12` authoritative; `gatest_11` alternates). Two **different** section mechanisms exist on the same implement bus — do not confuse them.

| Mechanism | Direction | CAN target | Section identity | ON vs OFF |
| :--- | :--- | :--- | :--- | :--- |
| **GRC EF00 feedback / operator toggles** | GRC → bus (sniff) | SA `0xCC`, PGN `0xEF00` | Per-section **element byte** in `051XX` frames | **Same element toggles** — no separate OFF code |
| **DDI 141 process data** | PUFVision → GRC (TX) | PDU1 dest `0xCC`, PGN `0xCB00` | **Bits 1–5** in one 16-bit value | **Bitmask** — clear bit = closed, set bit = open |

> **`0xFFFE` is not a CAN address.** It is the **all-sections-open bitmask** (bit 0 unused on the live Goldacres bus; bits 1–5 = L1→R1). The CAN destination for PUFVision section commands is always GRC source address **`0xCC`**. What changes per section state is the **value** inside the DDI 141 payload, not a different bus address per section.

##### Bit layout (5-section boom, center-out)

| Bit | Section | Role |
| :---: | :--- | :--- |
| 0 | — | Unused on live bus (always 0 in decoded masks) |
| 1 | **L1** | Left outer |
| 2 | **L2** | Left inner |
| 3 | **C** | Centre |
| 4 | **R2** | Right inner |
| 5 | **R1** | Right outer |

**Bitmask cheat sheet** (`1` = section OPEN):

| State | Mask (hex) | Notes |
| :--- | :---: | :--- |
| All sections OPEN | `0xFFFE` | Default idle / manual-test starting point |
| L1 closed only | `0xFFFC` | Bit 1 cleared |
| L2 closed only | `0xFFFA` | Bit 2 cleared |
| C closed only | `0xFFF6` | Bit 3 cleared |
| R2 closed only | `0xFFEE` | Bit 4 cleared |
| R1 closed only | `0xFFDE` | Bit 5 cleared |
| L1 + L2 closed | `0xFFF8` | Example multi-section close |
| All sections closed | `0xFFE0` | Bits 1–5 cleared |

Decoded **coarse summary** bitmaps on EF00 (feedback only, not used for PUFVision TX):

| Condition | `grc_ef00_coarse_bitmap` |
| :--- | :---: |
| Master OFF | `0xFFEE` |
| Master ON, all sections open | `0xFFF6` |
| Master ON, one or more sections closed | `0xFFE6` |

##### EF00 operator toggle elements (`gatest_12`)

When the operator toggles sections on the G5 display (**manual spray + master ON**), GRC emits proprietary frames on PGN `0xEF00`. Per-section commands use the `051XX` element byte inside `4F0B02020105XX00`. A paired broadcast mirror `4F0B02FF(XX+0x0D)` arrives in the same burst — **state is driven from `051XX` only** (parser ignores the FF mirror for toggles).

| Section | Toggle element (`051XX`) | Broadcast mirror (`FF…`) | Alternate elems (`gatest_11`) |
| :---: | :---: | :---: | :--- |
| **L1** | `0x1F` | `0x2C` | — |
| **L2** | `0x1E` | `0x2B` | — |
| **C** | `0x1C` | `0x29` | `0x0F` → `0x1C` |
| **R2** | `0x18` | `0x25` | — |
| **R1** | `0x10` | `0x1D` | `0x03` → `0x10` |

**Special EF00 frames (not per-section toggles):**

| Payload pattern | Meaning |
| :--- | :--- |
| `4F0B020201050000` (`050000`) | All sections ON reset (timer refresh / operator all-on) |
| `4F0B020200050000` (`020005`) | Accessory idle / manual timeout → all sections OFF in parser |
| `4F0601FF00` / `4F0601FF01` | Master OFF / Master ON |

Each `051XX` command is a **debounced toggle** (~8 repeats per ~200 ms burst; engine debounce `2.0 s`). The same element byte flips a section ON or OFF — there is no dedicated “OFF-only” element address.

##### PUFVision DDI 141 TX path (manual section test & vision)

PUFVision does **not** replay `051XX` toggles. At `SECTION`+ARM on the `goldacres_grc` profile, `send_section_commands()` transmits standard ISO 11783-10 process data:

| Field | Value |
| :--- | :--- |
| PGN | `0xCB00` (PDU1, PF `0xCB`) |
| Destination (PS) | GRC `0xCC` |
| Source (SA) | PUFVision claimed address (e.g. `0x80`) |
| DDI | `141` (`0x008D`, little-endian `8D 00`) |
| Value | 16-bit section bitmask (4-byte LE integer) |
| Element | `0` (entire boom — section discrimination is in the bitmask bits) |

**Manual section bench test** (UI: *Manual Section Test*):

- `SET_ENGINE_SIDE_SECTIONS:0` — disables vision-driven sections; engine accepts manual bitmap.
- `SET_SECTION_BITMAP:<decimal|0xhex>` — sets PUF intent using the `0xFFFE` base and bits 1–5.
- `SHADOW` — logs intent + AND preview, zero TX.
- `SECTION` + ARM — transmits DDI 141 at 10 Hz when cooperative AND-gate allows.

**Cooperative AND-gate:** `out_bitmap = puf_section_bitmap & jd_commanded_sections`. On Goldacres, `jd_commanded_sections` tracks the EF00-decoded GRC host mask while GRC is alive — PUFVision can only **close** sections the host left open.

##### Reading the GRC panel in the UI

| Display field | Source | Stays `0xFFFE` when… |
| :--- | :--- | :--- |
| **GRC Host (EF00 decode)** | Sniffed operator/GRC state on `0xEF00` | Operator has not toggled any section closed on the G5 |
| **PUF intent** | Manual section test or vision bitmap | All manual sections set OPEN (or vision sees no weeds) |
| **AND output** | `PUF intent & GRC host mask` | Either side has all bits open |

If **PUF intent** remains `0xFFFE` while closing individual sections in manual test, that indicates a UI/engine sync bug. If **GRC Host** stays `0xFFFE` during manual test, that is normal — PUFVision is not pressing the G5 toggles; EF00 only reflects display-operator actions.

### 10.2 John Deere 616R via GreenSeeker serial (Pathways G + E) — **Medium (~50–65%)**

- **Settled path (§4.3.2):** GreenSeeker whole-boom rate + Pathway E blanking only. CAN section injection, VPU emulation, and drafting-gate interceptor are ruled out for this machine.
- **Path**: PUFVision emulates a Trimble GreenSeeker RT200 on RS232 **COM Port 2** (38400-8N1, ASCII, 1 Hz), feeding a **finished whole-boom target rate** (not raw NDVI) the display ingests as a sanctioned prescription source.
- **End capability (realistic)**: **whole-boom rate modulation** — turn average rate up over weedy ground, down over clean ground. This is genuine ROI for blanket/variable-rate work.
- **What it does *not* give**: per-section or per-nozzle on/off. GreenSeeker is a single averaged rate channel; the JD See & Spray vision stack (Function 129 / Device Class 17 / Mfr 33, Ethernet image processors) owns spot section control and is closed.
- **Hard dependency**: requires a physical USB→RS232 adapter on COM2; this path **cannot** be tunnelled over ISOBUS (see §4.3). Also unconfirmed until tested on real hardware whether the Work Setup menu exposes GreenSeeker as a rate source without JD hardware presence.
- **Main risks**: exact RT200 line format (placeholder pending a real serial capture), and the display gating the menu behind hardware detection.

### 10.3 Summary

| Capability | Goldacres (CAN) | JD 616R (GreenSeeker serial) |
| :--- | :---: | :---: |
| Appear as authorized rate source | ✅ High | ⚠️ Likely (untested menu gate) |
| Whole-boom variable rate | ✅ | ✅ |
| **Whole-section spot on/off** | ✅ | ❌ (single averaged channel) |
| Per-nozzle | ⚠️ future (ExactApply/MNA) | ❌ |
| Physical interface | CAN adapter | USB→RS232 on COM2 |

---

## 11. Roadmap to Universal Whole-Section GoB Spot Spray

Goal: whole-section (not necessarily per-nozzle) Green-on-Brown spot spray across brands.

1. **Make Goldacres the reference platform.** Prove the full `OBSERVE → FULL` ladder there first; it is the most open path and gives true section spot control end-to-end. Lock down section cadence, hold-time/look-ahead tuning, and the cooperative AND-gate.
2. **Add speed-compensated look-ahead.** Today's `section_hold_time` gives trailing coverage; add a lead/lag based on ground speed and the camera→nozzle longitudinal offset (the JD diagnostics showed a ~-6500 mm GPS Y-offset) so a section fires as the weed reaches the nozzle line, not the camera line.
3. **616R: keep GreenSeeker for rate, accept no spot control there** until/unless a sanctioned section path appears. Use the whole-boom rate channel for ROI now.
4. **Brand-independent "standalone section driver" (over-the-horizon).** For machines that won't grant cooperative section authority, drive a dedicated section/relay path from PUFVision's own ECU (e.g., the AEF-certified MRS CC16-WP evaluated in Pathway C) so spot control bypasses host authority entirely. This decouples spot-spray capability from each OEM's closed TC-SC.
5. **Hardware horizon.** Migrate the inference + CAN driver to a dedicated edge node (CC16-WP + Jetson) once the Windows reference is proven, for deterministic timing independent of the laptop/UI.

---

## 12. 616R DTM System Architecture

This section folds the service-manual analysis from **TM174719** — *616R See & Spray Ultimate Diagnostic Technical Manual* (September 2024) — into the PUFVision address map. It is the authoritative reference for **how John Deere's proprietary CAN domains are wired**, not for ISOBUS Task Controller integration.

### 12.1 Source & Framing

| Aspect | TM174719 position | PUFVision relevance |
| :--- | :--- | :--- |
| **Primary networks** | JD proprietary CAN domains (VB1, IB1, IB2, IB3–IB6) | PUFVision's ISOBUS/J1939 integration targets **IB1 (Implement CAN)** only peripherally |
| **ISOBUS** | ISO connector (`X119`) on implement bus; not the See & Spray control plane | Standard TC-GEO / PGN 160 paths (§4) remain valid on IB1 |
| **ISOBUS VT** | Mentioned only for **GPS position viewing** on the display | PUFVision does not need VT emulation for the GreenSeeker serial path (§4.3) |
| **Ethernet** | See & Spray camera/video backbone (FAKRA + Ethernet switches) | Closed to PUFVision; see §3.5 Tier 2 and §12.6 |

> **Dependency rule (TM174719 p. 4360):** ExactApply **can** operate without See & Spray. See & Spray **cannot** operate without ExactApply. Any spot-spray integration that bypasses ExactApply/MNC is architecturally invalid on the 616R.

### 12.2 Multi-Tier CAN Architecture

John Deere labels machine CAN buses with internal designators. On the 616R Ultimate, the hierarchy is:

| Bus ID | JD name (manual) | Scope | Key nodes |
| :--: | :--- | :--- | :--- |
| **VB1** | Vehicle CAN bus 1 | Cab, engine, PDU, POD, OSD | Premium Server, MTG, OSDC, PDU, ATX |
| **IB1** | Implement CAN bus 2 | Sprayer solution + See & Spray gateway | GWC, MNC, PSSC, SSSC, BCHU, MTG, Premium Server |
| **IB2** | Boom CAN bus (BoomTrac) | Boom hydraulics + vision on boom | BCHU, VPUs, UHS, IMU, GWC |
| **IB3** | ExactApply subnet 1 | Far-left boom nozzles | MNC, VPUs 1–4, NZCs |
| **IB4** | ExactApply subnet 2 | Mid-left → left center frame | MNC, VPUs 2–6, NZCs |
| **IB5** | ExactApply subnet 3 | Right center → mid-right | MNC, VPUs 6–9, NZCs |
| **IB6** | ExactApply subnet 4 | Far-right boom | MNC, VPUs 8–10, NZCs |

**Gateway roster** — these controllers bridge domains; understanding them prevents bus-confusion during diagnostics:

| Gateway | Connects | Notes |
| :--- | :--- | :--- |
| **GWC** (`A725`, SA `0x94`) | IB1 ↔ IB2 (BoomTrac / See & Spray) | **Centrality:** without GWC on IB1, See & Spray is disabled on the display (§12.5). Never claim `0x94`. |
| **BCHU** (`A609`) | IB2 ↔ IB1 | Broadcasts BoomTrac sensor data (UHS, IMU, VPU status) to implement controllers. Manual acronym **BH1** = Boom Hydraulics 1. |
| **MNC** (`A4000`) | VB1 + IB1 + IB3–IB6 | ExactApply master; assigns NZC addresses each power cycle. |
| **Premium Server** (`A121`) + **MTG** (`A123`) | VB1 ↔ IB1 | Display data hub; MTG also carries JDLink telematics. MTG Ethernet faults can affect See & Spray video. |
| **OSDC** (`A101`) | VB1 + IB1 + OSD CAN + OSD LIN | Operator-station domain gateway (cab switches, CommandARM, HVAC LIN). |

```
  [Display]──Ethernet──[Premium Server / MTG]
       │                      │
       │                  VB1 │ IB1  (Vehicle / Implement)
       │                      │
       │                 [GWC 0x94]────IB2────[BCHU]──BoomTrac sensors
       │                      │              VPUs / UHS / IMU
       │                      │
       │                 [MNC 0x68]──IB3..IB6──[NZC × N per subnet]
       │                      │
       └── ISOBUS VT (GPS view only, peripheral)
```

Cross-reference: field-confirmed roster and avoid-set in **§3.2–§3.4**; legacy SR1/MNA/BH1 parameter indices in **§5**.

### 12.3 Controller Roster (Manual ↔ Field)

TM174719 acronyms (pp. 130–131) mapped to our Diagnostics Center names and hardware IDs:

| Manual abbrev. | Hardware ID | Field / likely SA | Network | Role |
| :--- | :---: | :---: | :--- | :--- |
| **GWC** | `A725` | **`0x94`** (confirmed) | IB1 + IB2 | See & Spray gateway; bridges implement ↔ BoomTrac. **Do not claim.** |
| **VPU** ×10 | `A711`–`A720` | dynamic (`0xA2` family in DTCs) | IB2 + IB3–IB6 | Vision processing; Hz daisy-chain physical ID (§12.4.1). |
| **MNC** | `A4000` | `0x68` / `0xD4` / `0xCD` / `0x69` | IB1 + IB3–IB6 | ExactApply master; NZC address assignment. |
| **NZC** | (per nozzle body) | assigned by MNC | IB3–IB6 | Individual nozzle control; valve B in Ultimate See & Spray mode. |
| **PSSC** | `A306` | likely **`0x17`** (SRC / SA 023) | IB1 | Primary solution system control — pump, pressure, rates (System 2). Maps to **SRC** spray-rate role in field diagnostics. |
| **SSSC** | `A307` | TBD | IB1 | Secondary solution system control (System 1). |
| **BCHU** / **BH1** | `A609` | `0x8A` (likely BHC) | IB2 + IB1 | Boom hydraulics gateway; BoomTrac height. |
| **PDU** | — | vehicle bus | VB1 | Corner post display; machine adjustments require PDU presence. |
| **ATX** | — | `0x1C` | VB1 | AutoTrac steering. |
| **MTG** | `A123` | TBD | VB1 + IB1 | JDLink telematics gateway. |
| **IBS** | — | TBD | IB1 | Indexed Boom Section — section indexing for spray mapping; investigate for cooperative section semantics. |

> **PSSC/SSSC vs. SRC:** TM174719 splits solution control into primary (`PSSC`, rear) and secondary (`SSSC`, left-rear) units. Field Diagnostics Center collapses spray-rate authority under **SRC** (`0x17`). Treat PSSC as the manual's name for the rate/pump controller PUFVision already monitors as SR1/SRC in **§5**.

### 12.4 Three Addressing Schemes (Critical)

The 616R uses **three independent addressing mechanisms**. Conflating them causes mis-diagnosis and unsafe injection.

#### 12.4.1 VPU Physical Addressing (Hz Frequency Daisy-Chain)

- **Mechanism:** After wakeup (engine running), VPUs self-identify by measuring an **address/sync circuit frequency** (Hz) passed in series. Center VPUs **5** and **6** are the origins; chains flow outward left (5→1) and right (6→10/"A").
- **Duration:** Up to **2 minutes** per power cycle (TM174719 p. 4356).
- **CAN claim:** Each VPU claims the **same J1939 SA** on BoomTrac CAN and its assigned ExactApply subnet(s).
- **Failure behaviour:**
  - Open circuit → downstream VPUs fail addressing; GWC DTCs for missing SA 162 (VPU family).
  - Single VPU with stored last-known location → uses cached position and outputs the respective Hz downstream.
  - VPU never established location → reports generic **"VPU"** on BoomTrac CAN; GWC faults (insufficient addressed VPUs).

**Abbreviated frequency table** (full table TM174719 pp. 4357–4358):

| VPU | TLA | Location | Freq In (Hz) | Freq Out (Hz) | Subnets |
| :--: | :--- | :--- | :---: | :---: | :--- |
| **1** | VS1/VP1 | Left boom | 695–700 | — | EA-1, BoomTrac |
| **2** | VS2/VP2 | Left boom | 721–731 | 693–703 | EA-1/2, BoomTrac |
| **5** | VS5/VP5 | Center frame | — | 786–796 | EA-2/3, BoomTrac |
| **6** | VS6/VPL | Center frame | — | 1395–1405 | EA-2/3, BoomTrac |
| **10** | VS10/VPA | Right boom | 1132–1142 | — | EA-4, BoomTrac |

Cross-reference: dynamic VPU NAME claims in the 128–247 pool — **§3.5**.

#### 12.4.2 NZC Addressing (MNC PWM ADDR Sync)

- **Mechanism:** On each power cycle, **MNC** assigns NZC CAN addresses via **four PWM ADDR sync lines** (`PWM ADDR1`–`PWM ADDR4`), one set per ExactApply subnet.
- **Direction:** Left → right within each subnet (TM174719 pp. 5685–5687).
- **After sequencing:** Sync lines become part of normal MNC↔NZC CAN traffic.
- **PUFVision implication:** NZC addresses are **ephemeral per key cycle** — sniffing SA assignments on IB3–IB6 requires capture immediately after wakeup.

#### 12.4.3 J1939 Source Address Monitoring (Decimal in DTCs)

JD diagnostic trouble codes reference SAs as **decimal strings**, not hex. The sniffer and log annotator should display both.

| Decimal SA (DTC) | Hex SA | Controller | In `jd_reserved_addresses`? |
| :--: | :--: | :--- | :---: |
| **023** | `0x17` | SRC / PSSC (spray rate) | ✅ §3.4 |
| **104** | `0x68` | MNC | ✅ §3.4 |
| **148** | `0x94` | GWC | ✅ §3.4 |
| **162** | `0xA2` | VPU family (×10 nodes) | ⚠️ monitor; not in avoid-set |
| **138** | `0x8A` | BCHU / BHC | ✅ §3.4 |

> **Diagnostic addresses ≠ J1939 SAs:** TLA parameter indices (e.g. GWC param `130`) remain separate — see §3.2 note.

### 12.5 GWC Centrality

The Gateway Control Unit is the **non-optional hub** for See & Spray on the 616R:

1. **Display gating:** If GWC is offline or absent from IB1, the See & Spray page and run-page modules are **grayed out** — See & Spray disabled (TM174719 p. 5681).
2. **Bus bridge:** GWC connects IB1 (implement) to IB2 (BoomTrac / See & Spray). VPUs report vision-spray module (VSM) status to GWC; GWC relays to implement-bus consumers.
3. **Wakeup chain:** `OSDC → PODC → GWC → Ethernet switches + VPUs` (switched 12 V relayed through GWC wakeup/shutdown lines).
4. **Operator UI:** GWC enables per-VPU/camera selection on the See & Spray screen; video returns via Ethernet switches to the Gen 4 display.
5. **Collision rule:** GWC SA is fixed at **`0x94`**. PUFVision's `jd_reserved_addresses` (§3.4) permanently excludes it.

**Suggested interlock:** treat GWC presence on IB1 (`0x94` alive, message counts incrementing) as a **pre-arm health check** before any implement-bus injection experiment.

### 12.6 Closed Vision → Nozzle Path

See & Spray Ultimate spot control follows a **closed, JD-owned pipeline** PUFVision cannot splice into without the full stack:

```
Camera ──FAKRA──► VPU (image processing)
                    │
                    ├──BoomTrac CAN (IB2)──► GWC ──► Display / implement bus
                    │
                    └──ExactApply CAN (IB3–IB6)──► MNC ──► NZC (valve B)
```

Key facts (TM174719 pp. 4362–4363, 5695):

- Each camera streams video over a **non-repairable FAKRA** cable (up to 6 GHz) to its VPU.
- VPUs 1, 2, 5, 6 each serve **eight cameras**; VPU 3 serves four; others vary by boom layout.
- VPU Ethernet feeds See & Spray switches for display video and reprogramming — **not** a rate-injection surface.
- In **Ultimate** mode, only **valve B** of each NZC responds to VPU spray commands.
- **PUFVision cannot emulate a VPU** without replicating Hz addressing, FAKRA ingest, BoomTrac height context, ExactApply subnet presence, and GWC handshake — i.e., the entire JD vision stack.

Cross-reference: Tier 1/2 split already noted in **§3.5**; whole-boom serial workaround in **§4.3.1**.

### 12.7 PUFVision Implications

| Topic | Assessment | Recommended path |
| :--- | :--- | :--- |
| **VPU emulation** | **Impossible** without full JD stack (§12.6) | Do not attempt NAME/SA mimic of Function 129 / Mfr 33 nodes |
| **Implement CAN injection** | **High risk** — GWC/MNC/PSSC arbitrate spray authority | Stay at `OBSERVE`/`SHADOW` on IB1; use Control Authority ladder (§9) |
| **GreenSeeker serial** | **Lowest-risk external rate path** | Pathway G (§4.3) — display-ingested prescription, no CAN TX |
| **Whole-boom blanking** | **Viable approximation** | Pathway E (§4.3.1) — rate 0 ↔ target rate modulation |
| **True per-section spot** | **Decision closed** — not reachable on 616R (§4.3.2); use Pathway G+E whole-boom only | Goldacres native CAN (§10.1) for per-section GoB; standalone driver (§11.4) over-the-horizon |
| **GWC health** | **Arm interlock candidate** | Require `0x94` alive before `RATE_ONLY` experiments |
| **IBS investigation** | **Open** | May clarify section-index semantics for future cooperative AND-gate work |

### 12.8 Manual Bookmark Pages (TM174719 PDF)

Quick-reference page index for field diagnostics and bench study:

| PDF pages | Topic |
| :---: | :--- |
| **130–131** | Acronym table (GWC, MNC, NZC, VPU, PSSC, SSSC, IBS, CAN bus 1/2/3) |
| **4246–4247** | Boom CAN (IB2) theory — BCHU gateway, VPU/UHS/IMU roster |
| **4250** | Implement CAN (IB1) theory — gateway list, node inventory |
| **4356–4358** | See & Spray addressing — Hz daisy-chain, full VPU frequency table |
| **4359–4361** | See & Spray / ExactApply CAN theory — subnets, terminators, MNC↔NZC |
| **4360** | CAN bus overview — VB1/IB1/IB2/IB3+ hierarchy; ExactApply-without-See&Spray rule |
| **4362–4363** | See & Spray Ethernet + FAKRA camera path |
| **5681** | GWC electrical theory — display gating, wakeup, IB1↔IB2 bridge |
| **5685–5687** | MNC + NZC theory — PWM ADDR sync, subnet topology |
| **5692–5694** | PSSC + SSSC (+ Premium Server) electrical theory |
| **5695** | VPU electrical theory — valve B, dual-CAN presence |

### 12.9 Suggested Compatibility Improvements

Derived from TM174719 architecture review; ordered by effort vs. safety payoff:

1. **Decimal SA labels in sniffer** — annotate RX frames with both hex and decimal SA (e.g. `0x17 / SA 023 SRC`) to match GWC/MNC/PDU DTC wording.
2. **GWC health as arm interlock** — extend §9.2 interlocks: if IB1 is attached and GWC (`0x94`) stops incrementing message counts, refuse `ARM` and log `gwc_missing`.
3. **BoomTrac vs. implement bus distinction** — tag decoded PGNs by bus ID (IB1 vs. IB2 vs. IB3–IB6) in telemetry; VPUs appear on multiple subnets with the same SA.
4. **VPU SA 162 watchlist** — monitor `0xA2` family presence separately from the avoid-set; ten missing-SA DTCs (GWC 002157–002171) indicate partial boom vision loss.
5. **IBS investigation** — determine whether Indexed Boom Section messages on IB1 expose cooperative section bitmaps usable for a future AND-gate without entering the closed VPU path.
6. **NZC post-wakeup capture window** — log first 120 s after key-on on IB3–IB6 to document ephemeral NZC address assignment for bench replay.

---

## 13. Brainstorm — GRC Health Interlock

*Design exploration only — no implementation yet. Intended to inform a future arm-gate before item #2 (GRC `0xCC` health interlock) is coded in `engine.py`.*

### 13.1 What proves GRC is alive?

On the Goldacres implement bus, the GreenStar Rate Controller appears as **GRC.001** at SA **`0xCC`** (§4.2). Three independent signals can corroborate liveness:

1. **Control Unit list** — GRC.001 present in the G5 Diagnostics Center roster with incrementing message counts.
2. **DDI 158 feedback** — actual applied flow returned on PGN 160 (`0x00A0`) from `0xCC` (§4.2, §7.1). `engine.py` already tracks `last_ddi158_rx_time`; staleness is a natural health metric.
3. **Diagnostic parameters** — GRC flow/pressure readings in the display's implement diagnostics (OMPFP10673 liquid-GRC manual) should move when sections are commanded ON at a non-zero Work Setup rate.

### 13.2 When to block ARM

Refuse `ARM` at `SECTION`/`FULL` (§9.1) when any of:

- **No `0xCC` RX** for longer than the existing bus-RX watchdog (`2.0 s`, §9.2) while the implement adapter is attached.
- **Stale DDI 158** — no flow feedback despite commanded sections ON and speed above the interlock floor.
- **Unexpected flow while sections commanded OFF** — GRC still dispensing at the minimum-flow floor (see §10.1 bring-up: *Minimum Flow Rate* must be 0 before blanking trials).

False **block** (refuse arm when GRC is fine) is preferable to false **arm** (actuate into a dead or misconfigured controller). The ladder already defaults to `OBSERVE`/`SHADOW`; an extra GRC gate extends §9.2 without replacing it.

### 13.3 Goldacres vs 616R

| Machine | Health anchor | Bus |
| :--- | :--- | :--- |
| **Goldacres** | GRC `0xCC` on implement CAN | Open cooperative TC-SC path (§10.1) |
| **616R** | GWC `0x94` on IB1 (§12.5) | Closed VPU/MNC stack; GRC may not be the section master |

The 616R analogue is already sketched in §12.9 item 2 (GWC alive before `RATE_ONLY`). A GRC-specific interlock belongs on the `goldacres_grc` profile only.

### 13.4 SHADOW validation & implementation sketch

Before the first `SECTION` arm on hardware, run **`SHADOW`** (§9.1): log PUFVision's commanded section bitmap and rate intent alongside live `jd_commanded_sections`, DDI 158, and sniffed GRC traffic. Compare commanded vs actual for at least one pass at working speed.

**Sketch in `engine.py` (design):** add `grc_health` to `interlock_status`; a `_service_grc_watchdog()` tick that sets `grc_missing` / `grc_flow_anomaly` when `0xCC` is silent or DDI 158 disagrees with section state; extend `_interlocks_ok()` and refuse `ARM` when tripped on `goldacres_grc`. Reuse `last_ddi158_rx_time` and existing `jdrc_address` auto-learn — no new PGNs required.

---

## 14. Brainstorm — CAN Section Interceptor ("Drafting Gate")

*Concept: an inline bus unit that intercepts section-control traffic, gates sections OFF until vision/weeds demand ON, reflects modified state back to the section-control master so the host does not fault, and records CSV for later conversion to an **As-Applied** map in John Deere **Operations Center**.*

### 14.1 Where this fits vs current PUFVision paths

| Path | Mechanism | Interceptor role |
| :--- | :--- | :--- |
| **Goldacres DDI 141 direct** (§10.1, §4) | PUFVision TX to GRC `0xCC` | Native injection already AND-gates sections; interceptor is redundant unless PUFVision cannot claim an address |
| **616R Pathway E** (§4.3.1) | GreenSeeker serial whole-boom blanking | No section bitmap on the wire — interceptor has nothing to gate |
| **616R Pathway G** (§4.3) | Rate prescription only | Same — rate channel, not per-section |
| **Standalone driver** (§11.4) | CC16-WP relay path | Functionally similar hardware (relay between command and valve) but bypasses host TC-SC entirely |

The interceptor is most interesting when the host **owns** section authority (display + GRC/SRC) but PUFVision must **subtract** coverage without joining the TC-SC server role — or when a second machine brand blocks direct DDI injection.

### 14.2 Topology: tap vs inline bridge

- **Listen-only tap** — safe for `OBSERVE`/`SHADOW` (§9); cannot modify frames. Good for CSV capture and rebound-problem study, not for gating.
- **Inline bridge/gateway** — two CAN ports; terminates and re-originates frames with altered section bits. Required for the "drafting gate." Must preserve SA, PGN cadence, and transport sequencing or the master detects a peer dropout.

**Bus choice:**

- **Goldacres implement CAN** — open, GRC cooperative; inline bridge between display TC client traffic and GRC `0xCC` is feasible if wiring access exists.
- **616R IB1** — GWC/MNC/PSSC arbitrate spray authority (§12.7); inline manipulation risks fighting SRC `0x17` and triggering GWC DTCs. **High risk** — prefer serial rate path or Goldacres reference first.
- **616R IB2** (BoomTrac) — closed VPU→NZC path (§12.6); interceptor would need ExactApply subnet knowledge. Not recommended without full stack emulation.

### 14.3 What to intercept

Candidate frames (priority order for Goldacres):

1. **TC-SC process data DDI 141** — section control state to GRC (what PUFVision already sends in `send_section_commands`, §9.3).
2. **PGN `0xCB00`** — ISO 11783-10 process data container for section/rate DDIs.
3. **Host-commanded sections** — display-internal section bitmap reflected on the bus as `jd_commanded_sections` (sniffed, not originated by PUFVision).

The gate logic: `applied_bitmap = host_commanded AND vision_weed_bitmap` (same cooperative semantics as §9.1). Sections stay OFF until weeds are detected in the corresponding boom zone.

### 14.4 The rebound problem

The section-control **master** (GRC on Goldacres, SRC/PSSC on 616R) expects consistent **feedback**: section valve state, flow meter movement, and TC-SC "actual work state" must agree with commands. If the interceptor only blocks outbound ON commands but does not **reflect** a coherent OFF state back to the display:

- **Unexpected flow DTCs** — flow continues while the display believes sections are ON (minimum-flow floor, §10.1).
- **Section state mismatch** — TC-SC handshake stalls; headland or boundary logic may force all sections closed.
- **Timeout / dropout** — master stops seeing expected process-data cadence (~10 Hz section loop, §9.3) and fails safe.

A working interceptor must **re-originates** modified DDI 141 (and, if required, echoed feedback DDI) so both downstream (GRC) and upstream (display TC client) see a consistent world. This is harder than PUFVision's native path, where we are already the TC client originator.

### 14.5 Hardware options

| Platform | Pros | Cons |
| :--- | :--- | :--- |
| **ESP32 + dual CAN** | Low cost, deterministic MCU loop | Limited buffer depth; ISO-TP if DDOP needed |
| **Raspberry Pi + SocketCAN** | Fast prototyping, CSV/logging easy | Linux jitter on 10 Hz gate |
| **Dedicated MCU (STM32)** | Production-grade timing | More firmware effort |
| **CC16-WP style relay** (§11.4) | AEF-certified section hardware | Bypasses CAN semantics — different product |

### 14.6 Latency, cadence, and control authority

- Section loop today runs at **10 Hz** (`update_vision_sections`, §9.3) with **0.5 s** default hold-time; 616R ON/OFF delays are **0.5 s / 0.1 s** (§3.3). The interceptor must not add more than one frame period of delay or trailing coverage suffers.
- **Look-ahead** (§11.2) still applies — the gate opens ahead of nozzle arrival, not camera arrival.
- **Legal/safety:** the interceptor is **not** a bypass around the Control Authority ladder (§9). Treat it as an external actuator on the `SHADOW` → `SECTION` path: `OBSERVE` capture first, then gated TX only when armed. Operator master ON and host section switches remain authoritative; vision may only subtract.

### 14.7 CSV schema sketch (As-Applied precursor)

High-frequency log for later georeferencing and Ops Center import:

```
timestamp,lat,lon,speed_kmh,section_bitmap_commanded,section_bitmap_applied,rate_target_l_ha,rate_actual_l_min,weed_detected_mask,interlock_state,grc_alive,notes
```

- **GPS columns** — populate from PGN 65267 / serial NMEA if available (§5.4); nullable on bench.
- **Bitmaps** — 16-bit hex or per-bit columns matching configured section count (§10.1), not assumed 10.
- **Ops Center shape** — *open item.* JDOC typically ingests field operations via **MyJohnDeere** upload (shapefile, GeoJSON, or proprietary task layer); exact as-applied vs as-planned schema for third-party CSV is not confirmed here. Likely path: export georeferenced polygons or point layers per applied section, then manual or API upload to the field operation layer. Research JDOC import spec before building converter.

### 14.8 Feasibility and pros/cons vs native injection

**Goldacres — feasible.** Open implement CAN, cooperative GRC, existing PUFVision `goldacres_grc` profile proves DDI 141 injection. Interceptor adds value only if address-claim conflicts or TC-SC pairing blocks PUFVision from transmitting; otherwise native injection is simpler and already AND-gated.

**616R — poor fit; decision closed (§4.3.2).** Closed VPU stack (§12.6), GWC centrality (§12.5), and serial-only rate path (§4.3) mean an IB1 interceptor fights SRC/GWC without granting per-nozzle spot. Pathways G + E whole-boom blanking is the settled 616R program; interceptor work is Goldacres-only unless IBS (§12.3) later exposes a cooperative section bitmap.

| | Native PUFVision injection | CAN interceptor |
| :--- | :--- | :--- |
| **Complexity** | Software-only on existing adapter | Hardware bridge + rebound firmware |
| **Host compatibility** | Requires address claim + TC client | May work as "transparent" filter |
| **Ops Center CSV** | Already have `myops_telemetry.csv` (§7.2) | Dedicated high-res gate log |
| **Risk** | Gated by §9 ladder | Bus fault if bridge crashes mid-row |

### 14.9 Recommended next steps

1. **`OBSERVE` capture on Goldacres** — record all DDI 141 / `0xCB00` / `0xCC` traffic during a manual section toggle pass; document rebound frames the display expects.
2. **Prototype gate logic on Virtual Bus** — implement AND-gate in the existing simulator before any inline hardware; validate §10.1 section-count mapping.
3. **Defer 616R interceptor** — pursue GreenSeeker rate ROI (§10.2) and GWC health logging (§12.9) instead; revisit only if IBS (§12.3) exposes a cooperative section bitmap on IB1.

---

## 15. Timing, Security & Anti-Slip Strategy

John Deere "security lockouts" for man-in-the-middle (MITM) or piggyback systems are not a single cryptographic gate — they are a stack of **role enforcement, feedback consistency, and timing contracts**. PUFVision avoids fighting those contracts where possible; where timing matters, we use **measured margins**, not injection squeezed into proprietary frame gaps.

### 15.1 What John Deere Is Actually Locking Down

| Layer | Mechanism | Piggyback / MITM risk |
| :--- | :--- | :--- |
| **Role / architecture** | TC server owns section setpoints; implement executes and reports back | Inline tap between display and GRC without a recognised TC client role |
| **Feedback agreement** | Flow, valve state, and TC-SC "actual work state" must agree with commands | Block ON without echoing coherent OFF → DTCs, headland failsafe, master OFF |
| **Cadence** | Section/rate process data expected at ~10 Hz (§9.3) | Bridge latency → dropout, fail-safe |
| **Identity** | NAME / SA collision, TC-SC pairing state | Spoofing or claiming a peer address (see §3.4 — `0xCC` avoid-set) |
| **Newer hardware** | 500 kbps / 2 Mbps CAN-FD proprietary buses (§3.0) | **Less** timing slack than Gen4 / Goldacres classic 250k — piggyback window shrinks |

### 15.2 Platform Strategy (Avoid MITM as Default)

| Platform | Primary path | MITM / interceptor |
| :--- | :--- | :--- |
| **Goldacres G5 + GRC** | Native **DDI 141 originator** to GRC `0xCC` (§10.1) — legitimate TC client, cooperative AND-gate | Fallback of last resort only if address claim or TC pairing blocks native TX (§14.8) |
| **616R** | **GreenSeeker serial** rate + whole-boom blanking (§4.3.2) — sanctioned external input | **Ruled out** — closed VPU stack, GWC/SRC rebound on IB1 (§14.8) |
| **Newer JD (CAN-FD)** | Sniff-only until bus profile confirmed (§3.0) | Assume closed; do not plan piggyback without FD-capable bridge + full rebound firmware |

**Design principle:** Be a **recognised originator** (Goldacres) or a **sanctioned serial source** (616R). Do not depend on "older hardware is slower so we have more time to inject" as the production safety basis — characterise margins on target hardware, design for newer FD timing.

### 15.3 Margin-Based Timing (Lead Early, Hold Late)

Do not ride the edge of proprietary signal arrival windows. Command with **lead and trail envelopes** derived from measured latency.

**Pipeline:**

```
Camera detect → look-ahead lead → hold-time trail → cooperative AND → 10 Hz TX → EF00 / DDI 158 feedback
```

| Parameter | Current value | Role |
| :--- | :---: | :--- |
| `section_hold_time` | `0.5 s` (§9.3) | **Trailing** margin — section stays OPEN after weed leaves camera FOV |
| 616R section ON / OFF delay | `0.5 s` / `0.1 s` (§3.3) | Host valve latency budget (616R reference) |
| Section TX / vision loop | **10 Hz** | One missed tick = **100 ms** slip |
| EF00 toggle debounce | `2.0 s` | Sniff-side only (operator `051XX` bursts) — not the PUFVision command path |
| GreenSeeker serial | **1 Hz** | 616R rate channel — whole-boom, not per-section |

**Tuning rule (Goldacres section path):**

```
lead_time  = (camera_to_nozzle_m / speed_m_s) + valve_on_delay + 1 × TX_period
trail_time = section_hold_time + valve_off_delay
```

- **Lead** (planned, §11.2): open section before weed reaches nozzle line, not when it leaves camera. Uses FEF1 wheel speed + camera→nozzle longitudinal offset (~6500 mm from JD diagnostics).
- **Trail**: `section_hold_time` covers detection flicker and valve close lag.
- **Fixed margin**: always budget **≥1 full TX period (100 ms)** plus documented valve delays — never cut to zero.

### 15.4 SHADOW Validation — Measure Before You Arm

Before `SECTION` + ARM on hardware, run **`SHADOW`** (§9.1) at working speed and build latency histograms from `shadow_channels.csv`:

| Column | Use |
| :--- | :--- |
| `vision_bitmap` | PUFVision intent |
| `shadow_and_bitmap` | After cooperative AND |
| `grc_ef00_section_bitmap` / DDI 158 | Host / actuator feedback |
| `speed_kmh` | Bin by speed band (e.g. 4 / 8 / 12 km/h) |

**Exit criteria:** p95 slip (intent → feedback) must fit inside lead/trail envelopes. If p95 exceeds `section_hold_time`, widen hold-time or lead — do not increase injection aggressiveness.

### 15.5 Cooperative AND — Subtract Only, Never Fight the Host

```text
applied_bitmap = puf_section_bitmap & jd_commanded_sections
```

PUFVision may only **close** sections the host left open (§9.1, §10.1.1). This avoids the worst rebound cases (§14.4): display believes ON, flow shows OFF, minimum-flow floor DTCs. MITM that blocks outbound frames without **re-originating feedback both directions** is where JD lockouts bite hardest.

### 15.6 Interlocks as Slip Detectors

| Interlock | Trip | Response | Catches |
| :--- | :--- | :--- | :--- |
| **Speed** | `< 0.5 km/h` | Force-safe; no demote | Normal stop |
| **Bus RX** | `> 2.0 s` silence | Force-safe + demote to `SHADOW` | Adapter drop, bus fault |
| **UI heartbeat** | `> 3.0 s` | Force-safe + demote to `SHADOW` | Renderer freeze |
| **GRC health** (planned, §13) | `0xCC` silent or DDI 158 disagrees with commanded sections | Refuse ARM / demote | Command sent, actuator didn't follow |

Treat feedback divergence as a **timing or authority fault**, not a cue to inject faster.

### 15.7 MITM / Interceptor Bar (Goldacres Fallback Only)

If native DDI 141 injection is blocked on a specific machine, §14 defines the minimum bar for an inline bridge:

1. **Inline bridge** (two CAN ports) — listen-only tap cannot gate (§14.2).
2. **Re-originates** modified DDI 141 **and** echoed feedback so display + GRC agree (§14.4).
3. **Preserves** source address, PGN cadence, ~10 Hz — bridge adds **< 1 frame (100 ms)** or trailing coverage suffers (§14.6).
4. **Dedicated MCU** (STM32 class) preferred over Raspberry Pi — Linux jitter on a 10 Hz gate causes message slip (§14.5).
5. Still behind the **Control Authority ladder** (§9) — `OBSERVE` capture first, gated TX only when armed.

**616R:** do not pursue MITM on IB1–IB6; pursue GreenSeeker rate ROI (§10.2) instead.

### 15.8 Recommended Next Steps

1. **Goldacres native path first** — manual `SECTION` bench (master OFF, §10.1.1), then `SHADOW` at working speed with histogram analysis (§15.4).
2. **Implement speed-compensated look-ahead** — camera→nozzle offset + FEF1; tune per speed band from shadow logs (§11.2, §15.3).
3. **Code GRC health interlock** — extend `interlock_status`; refuse ARM when feedback disagrees (§13.4 sketch).
4. **Defer MITM hardware** unless native claim/pairing fails on a specific Goldacres unit; prototype AND-gate on virtual bus first (§14.9).
5. **Document per-machine latency table** — after first field pass, record p50/p95 lead and trail at each target speed; store in session metadata / `DEV_NOTES.md`.
