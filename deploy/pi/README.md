# Raspberry Pi — ISOBUS WiFi gateway

Edge box: **isolated CAN HAT** on implement bus (X119, **250 kbps classic CAN**) → **UDP**
over cab WiFi → laptop/tablet running `isobus_wifi client --gps`.

**Safety:** RX-only. No CAN TX. GPS / OBSERVE path only — not for section actuation.

---

## Supported hardware (tested patterns)

| HAT | Interface | Notes |
| :-- | :-- | :-- |
| Waveshare 2-CH CAN HAT | `can0` | SPI MCP2515 — use **isolated** variant for field |
| PiCAN 2 / 3 | `can0` | SocketCAN native |
| Sequent Microsystems ISCAN | `can0` | Isolated ISO1050 transceiver |
| CANable on Pi USB | `/dev/ttyACM0` | slcan: `--interface /dev/ttyACM0` |

Use an **isolated** transceiver on the implement bus — ground loops between tractor
and Pi are common.

---

## 1. OS setup

```bash
sudo apt update
sudo apt install -y python3 python3-pip python3-venv can-utils
```

Enable SPI / overlay for your HAT (example Waveshare — check your HAT docs):

```bash
# /boot/firmware/config.txt (Bookworm) or /boot/config.txt
# dtparam=spi=on
# dtoverlay=mcp2515-can0,oscillator=16000000,interrupt=25
# dtoverlay=spi-bcm2835-overlay
sudo reboot
```

Bring up SocketCAN @ 250 kbps:

```bash
sudo ip link set can0 down 2>/dev/null || true
sudo ip link set can0 type can bitrate 250000 restart-ms 100
sudo ip link set can0 up
candump can0   # verify traffic on implement connector
```

---

## 2. Install gateway (Python venv)

```bash
cd /opt
sudo git clone <your-repo> pufworks-isobus   # or rsync from workshop
cd pufworks-isobus
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Copy config:

```bash
sudo cp deploy/pi/can_wifi_gateway.json /etc/pufworks/can_wifi_gateway.json
sudo mkdir -p /etc/pufworks
```

Edit `/etc/pufworks/can_wifi_gateway.json` if using unicast to a fixed tablet IP.

---

## 3. systemd service

```bash
sudo cp deploy/pi/can-wifi-gateway.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable can-wifi-gateway
sudo systemctl start can-wifi-gateway
journalctl -u can-wifi-gateway -f
```

Manual run:

```bash
source /opt/pufworks-isobus/.venv/bin/activate
python scripts/isobus_wifi.py gateway --config /etc/pufworks/can_wifi_gateway.json
```

---

## 4. Cab client (Windows laptop)

```powershell
# Python
python C:\Projects\PUFworks-isobus\scripts\isobus_wifi.py client --gps --nmea-udp 127.0.0.1:9999

# Or standalone exe (see scripts/build_can_wifi.ps1)
dist\isobus_wifi\isobus_wifi.exe client --gps
```

AgValoniaGPS / AgIO: point GPS UDP to `127.0.0.1:9999`.

For **unicast-only** Pi → one tablet, set `"unicast_client": "192.168.4.2"` in config
and run client with `--multicast none`.

---

## 5. WiFi topology

```
Implement X119 ──[isolated CAN HAT]── Pi (gateway)
                                        │
                                   UDP :5578
                                        │
                    Cab WiFi AP ────────┴──── Windows tablet (client --gps)
```

Pi can be:
- **WiFi client** on the cab router (unicast to tablet IP), or
- **WiFi AP** (`hostapd`) with multicast (default `239.255.42.1`)

Prefer **5 GHz** or wired Ethernet backhaul if the cab router supports it — UDP
drops affect GPS smoothness, not safety (no actuation on this path).

---

## 6. Troubleshooting

| Symptom | Check |
| :-- | :-- |
| No `candump` traffic | Bitrate 250k, correct X119 pins, termination |
| Gateway runs, client stale | Firewall UDP 5578, multicast routing, same subnet |
| GPS fix never valid | ATX 0x1C on bus; try `--gnss-debug` on client |
| High CPU | `--max-hz 200` on gateway to cap flood PGNs |

---

See also: `docs/CAN_WIFI.md`, `SAFETY.md` (RX-only seal).
