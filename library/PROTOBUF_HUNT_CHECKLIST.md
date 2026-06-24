# Protobuf / nanopb Hunt Checklist

**Goal:** Decide whether an unknown CAN payload is **standard protobuf wire format** (possibly **nanopb** on FreeRTOS ECUs) vs **JD fixed element**, **bitmap**, or **padding**.

**Context:** JD *Installed Features* appendix lists **nanopb-0.3.9**, **protobuf 2.5 / 3.18**, **protobuf-c** on machine components; display app adds **rapidjson**, **GDAL**, **MQTT** (see `library/JD_THIRD_PARTY_SOFTWARE.md`).

**Tool:** `python scripts/probe_protobuf.py recordings/<session> --sa … --pgn …`

---

## 0. When to bother (and when not to)

### Good protobuf hunt targets
| Target | SA | PGN | Why |
| :--- | :--- | :--- | :--- |
| Unknown SRC EF00 tail bytes | `0xE1` | `0xEF00` | After 3-byte element id |
| MNC CB00 bytes 4–7 | `0xD4` | `0xCB00` | After prefix4 lane+suffix grammar |
| SA `0xBA` traffic | `0xBA` | `0xE700` | Unnamed high-volume proprietary |
| NZC / DISP proprietary | `0xCD`/`0xF0` | `0xFFF4` etc. | High unique count |

### Skip protobuf hunt (already decoded or wrong shape)
| Payload | Verdict |
| :--- | :--- |
| `4F0101`, `4F0B06`, `F43401` | **JD EF00 elements** — fixed layout, not protobuf |
| `F70400FFFFFFFFFF` | **Idle filler** — constant bytes |
| MNC prefix4 `93110200` | **Lane multiplex** — byte grammar known |
| DISP `F107CC` / `F002CC` / `F10FFF` | **10 Hz liveness** — fixed |
| Entropy ~8 bits/byte every frame | Encrypted or compressed — not plain protobuf |

---

## 1. Pre-flight (5 min, desk)

- [ ] Session has `frames.csv` (recorder or sniff).
- [ ] Note **machine state**: spray / transport / master OFF / pressure mode.
- [ ] Open `library/src_ef00_catalog.json` — list **unknown** prefixes.
- [ ] Open `library/mnc_cb00_map.json` — note suffix families.
- [ ] Install optional: **`protoc`** on PATH (for `--decode_raw`).

---

## 2. Quick probe (per SA + PGN)

```powershell
cd C:\Projects\PUFworks-isobus

# SRC unknown idle family
python scripts/probe_protobuf.py recordings\<session> --sa 0xE1 --pgn 0xEF00 --prefix F70400

# SRC spray churn (compare score vs idle)
python scripts/probe_protobuf.py recordings\<session> --sa 0xE1 --pgn 0xEF00 --prefix 4F1401

# MNC full payload
python scripts/probe_protobuf.py recordings\<session> --sa 0xD4 --pgn 0xCB00 --limit 40

# MNC skip known prefix4 — probe trailing bytes only
python scripts/probe_protobuf.py recordings\<session> --sa 0xD4 --pgn 0xCB00 --offset 4

# Top hit through protoc if installed
python scripts/probe_protobuf.py recordings\<session> --sa 0xE1 --pgn 0xEF00 --prefix F70400 --protoc
```

### Score guide (`probe_protobuf.py`)

| Score | status | Likely meaning |
| :---: | :--- | :--- |
| **≥ 70** | `full` | Strong protobuf — pursue `.proto` reverse or field correlation |
| **40–69** | `full`/`partial` | Possible nanopb subset or message + trailing padding |
| **< 40** | any | Fixed JD layout, bitmap, or random fill |

**False positives:** score ≥ 70 on **≤ 4 bytes** or **frames < 10** is usually accidental tag alignment — require high frame count or operator-correlated varint change before logging as protobuf.

---

## 3. Manual wire-format checks (no .proto)

Protobuf field key = `(field_number << 3) | wire_type`.

| wire_type | Meaning |
| :---: | :--- |
| 0 | varint (int32/uint32/bool/enum) |
| 1 | 64-bit fixed |
| 2 | length-delimited (string, bytes, embedded message) |
| 5 | 32-bit fixed |

### Checklist per payload hex
- [ ] First byte is **not** always `0x4F` / `0xF4` (JD element markers → stop).
- [ ] Can parse **2+ consecutive tags** without wire_type 3/4/6/7.
- [ ] **Varint fields** change smoothly frame-to-frame (counters, rates).
- [ ] **Length-delimited** fields (wire 2) have length byte ≤ remaining bytes.
- [ ] Same **field numbers** repeat across frames at same offset.
- [ ] `protoc --decode_raw` prints numbered fields (not empty / error).

### Negative signals (NOT protobuf)
- [ ] Repeating `FF FF FF` tail (`F70400`, `F00DFF`).
- [ ] Single u16 at fixed offset scales as `/10` or `/256` (J1939-style).
- [ ] Nibble bitmap flips (`4F0B0602` section map).
- [ ] Prefix4 lane key + suffix (`xx110200`) — grammar in `mnc_cb00_map.json`.

---

## 4. Nanopb-specific hints (embedded ECUs)

nanopb often produces:
- [ ] **Small messages** (≤ 64 B) with **few fields** (1–6 tags).
- [ ] **No delimited submessages** if `PB_NO_ERRMSG` / static alloc — mostly varint + fixed32.
- [ ] **Field numbers 1–15** common (single-byte tags).
- [ ] **Enum-like varints** 0/1/2 only.
- [ ] Identical **tag sequence** across frames; only **one varint** changes (live value).

If tags parse but **field numbers jump randomly** between frames → probably not one message type.

---

## 5. Correlation passes (turn unknown into decode)

Run after a candidate scores ≥ 40.

| Correlate with | Method | Confirms field role |
| :--- | :--- | :--- |
| **Speed** | `decode_gps_track.py` + timestamp merge | motion-linked varint |
| **Rate** | `decode_src_ef00.py` `4F0101` timeline | rate-linked |
| **Pressure mode** | `F43401` / `F10E5C` vs `F10E4C` | mode switch |
| **MNC suffix** | `probe_protobuf.py --offset 4` on CB00 windows | ASC vs spray |
| **Section bitmap** | `decode_section_bitmap.py` | section-linked bytes |

```powershell
# Slowdown window (ASC suffixes) — already validated spray_live +195–215 s
python scripts/decode_disp.py recordings\<session> --window 195 215 -o library\disp_mnc_slowdown_window.json
python scripts/probe_protobuf.py recordings\<session> --sa 0xD4 --pgn 0xCB00 --offset 4 --min-score 40
```

---

## 6. Priority queue (project backlog)

Work top-down; **stop** when score stays < 40 after offset sweep.

| Priority | Payload | Action |
| :---: | :--- | :--- |
| 1 | **MNC CB00 bytes 4–7** | `--offset 4`; compare steady `110200` vs ASC `00A5xx` windows |
| 2 | **SRC `F70400`** | Expect **fail** (padding) — documents negative example |
| 3 | **SRC `4F1401` / `4F3601` tail** | `--offset 6`; paired ~1 Hz metrics |
| 4 | **SA `0xBA` `0xE700`** | Full payload probe; identify on Diagnostics first |
| 5 | **DISP `0xFFF4` `650F00…`** | High unique count — UI state, may be protobuf or struct array |
| 6 | **NZC `0xFFF4`** | Per-nozzle path; needs subnet capture later |

---

## 7. Field capture to unlock hunt

| Label | Duration | Purpose |
| :--- | :---: | :--- |
| `616r_transport` | 5–10 min | Idle baseline — negative control for protobuf scores |
| `616r_rate_pressure_ab` | 4 min | Rate then 1000 kPa — toggles `F10E4C` ↔ `F10E5C` |
| `616r_headland_live` | 60–90 s | MNC `00A5xx` + possible protobuf in CB00 tail |
| `616r_sec_R5` | 25 s | Section toggle — correlate varints to bitmap |

Always:
```powershell
.\scripts\field_sniff_616r.ps1 -Interface COM2 -SniffMode 616r -Label "<label>" -Record
python scripts/probe_protobuf.py recordings\<label> --sa 0xD4 --pgn 0xCB00 --offset 4
python scripts/decode_field_library.py --live recordings\<label>
```

---

## 8. If protobuf is confirmed — next steps

1. **Dump top 20 unique payloads** to `recordings/<session>/protobuf_candidates_<sa>_<pgn>.txt` (hex + score).
2. **Track field numbers** that change with operator actions → name in `SPRAY_DECODE.md`.
3. **Do not** block on finding official `.proto` — JD rarely ships them; field correlation is enough for shadow/recorder use.
4. If `protoc --decode_raw` shows stable schema, add a **minimal decoder** beside `decode_src_ef00.py` (out of scope until score ≥ 70 on real data).

---

## 9. Expected outcomes (honest priors)

| Area | Protobuf likelihood | Most likely actual encoding |
| :--- | :---: | :--- |
| SRC EF00 `4Fxx01` elements | **Low** | JD fixed element + u16 |
| SRC `F10Exx` pressure family | **Low** | Fixed counter + kPa scaled bytes |
| MNC CB00 tail | **Medium** | Possibly struct; test with `--offset 4` |
| SA `0xBA` E700 | **Medium–High** | Unknown proprietary — best raw hunt |
| Cloud/MQTT path | **High** but **not on X119** | aws-iot / mosquitto on display |

---

## Related files

| File | Role |
| :--- | :--- |
| `scripts/probe_protobuf.py` | Wire-tag scorer + optional `protoc --decode_raw` |
| `library/JD_THIRD_PARTY_SOFTWARE.md` | nanopb / protobuf / lwIP stack map |
| `library/src_ef00_catalog.json` | Unknown SRC prefix list |
| `library/mnc_cb00_map.json` | MNC lane/suffix grammar |
| `library/PROTOBUF_HUNT_CHECKLIST.md` | This document |
