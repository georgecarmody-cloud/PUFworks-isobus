# SAFETY.md — PUFworks-isobus

These rules are load-bearing. Do not bypass them, and do not merge changes that
weaken them without an explicit field-owner decision recorded in
`JD_ISOBUS_MAP.md`.

## Control Authority ladder (enforced in `_tx_allowed`)

The engine **boots in `OBSERVE`** — zero CAN TX, pure sniffer.

| Rung | TX allowed |
| :--- | :--- |
| `OBSERVE` | Nothing |
| `ANNOUNCE` | Address claim, WSM, TC announce, VT handshake |
| `SHADOW` | Same as ANNOUNCE; sections computed + logged only |
| `RATE_ONLY` | + DDI 157 rate, only while `ARM`ed |
| `SECTION` / `FULL` | + section bitmap, only while `ARM`ed |

Every TX path calls `_tx_allowed(kind)`. New TX paths MUST be gated the same way.

## Interlocks (force-safe, evaluated every 100 ms)

- Speed < 0.5 km/h → rate 0, sections closed (no demote — normal operation)
- No CAN RX > 2 s while armed → demote to `SHADOW`, disarm
- No `UI_HEARTBEAT` > 3 s while armed → demote to `SHADOW`, disarm
- **Vision staleness** (new in the split): once a `SectionBitmapV1` feed has been
  seen, >300 ms without a fresh message → all sections CLOSED; while armed, this
  demotes to `SHADOW`. A stale feed never falls back to a manual vector and
  never holds the last bitmap. Silence from vision means the publisher is
  dead, never "no targets" — vision must publish `0x0` at fixed rate.

## Platform decisions (closed — do not re-open without user request)

- **616R**: GreenSeeker serial (Pathway G) + whole-boom blanking (Pathway E)
  only. **No CAN section injection.** The blanking detection input is the same
  `SectionBitmapV1` feed (`vision_weeds_present()`).
- **Goldacres (`goldacres_grc`)**: DDI 141 sections to GRC `0xCC`; DDI 157 rate
  TX suppressed (rate fixed in Work Setup). Arm from `SECTION`+.

## Address hygiene

Never claim a JD-reserved SA (`jd_reserved_addresses` in `bus_engine.py`),
including GRC `0xCC` — we transmit TO it, never AS it.

## Session recorder

Recording is allowed at `OBSERVE`–`SHADOW` only; raising authority above
`SHADOW` auto-stops an active session. Recordings stay out of git.

## UI host obligations

Whatever UI hosts this engine (bench UI now, integrator shell later) MUST send
`UI_HEARTBEAT` at 1 Hz while any actuation rung is armed, and MUST keep
`confirm()`-style gates on rungs `RATE_ONLY` and above.
