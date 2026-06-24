# John Deere 4600 CommandCenter — Third Party Software Appendix

**Source:** In-cab display → Legal / Third Party Software screens (photos 2026-06-15).  
**Titles seen:** *4600 CommandCenter and 4640 Universal Display - Application - Third Party Software License - 25-3*; *Board Services*; *Installed Features - Third Party Software Notices - 25-3*.

Use this as a **stack map**, not a decode table. It explains what the display and machine ECUs are built from — useful for guessing serialization (JSON, protobuf, XML), networking beyond CAN, and where GIS/rate logic might live.

---

## Tier A — Directly relevant to PUFworks / ISOBUS / CAN sniffing

| Package | Version(s) | Why it matters |
| :--- | :--- | :--- |
| **json-c** | 0.12 | JSON on display/board — aligns with our `GpsFixV2`, library JSON maps |
| **rapidjson** | 1.1.0 | C++ JSON — likely internal config/telemetry interchange |
| **protobuf** / **protobuf-c** / **nanopb** | 2.5.0, 3.18.3, 1.2.1, 0.3.9 | **Structured binary messages** on ECUs — candidate encoding for proprietary PGN payloads beyond raw J1939 bytes |
| **postgresql-protobuf** | 2.6.0 | Protobuf + DB — task/prescription storage pattern |
| **libxml2** / **lxml** / **xerces-c** | 2.9.2 / 2.9.5 / 3.1.2 | XML — ISOBUS **DDOP / object pool** and TC-GEO often XML-derived |
| **libpcap** / **WinPcap** | 1.0.0 / 4.0 | Packet capture on **Ethernet** legs (not X119 CAN tap) |
| **tcpdump** | 4.7.4 | Same — if you ever sniff VB1 / service port |
| **lwIP** | 2.0.3, 2.1.0 | TCP/IP on **implement ECUs** — explains non-CAN paths |
| **mosquitto** | 2.0.14, 2.0.21 | **MQTT** — cloud/telematics parallel to CAN |
| **python-paho-mqtt** | 1.5.0 | Display-side MQTT client |
| **awsiotcppsdk** | 1.3.0 | **AWS IoT** — JDLink-style uplink, not implement bus |
| **amazon-kinesis-video-streams-*** | 3.3.1 / 1.7.3 | Video streaming (cameras / See & Spray context) |
| **libsqlite3** | 3.45.01 / 3.3.29 | On-device **task, boundary, log** storage |
| **GDAL / Fiona / geos / GeographicLib / proj / pyproj / geopandas / Shapely / shapelib / h3 / python-utm** | various | Full **GIS stack** — headlands, boundaries, ASC geometry live here, not in raw CB00 bytes |
| **python-rtree / spatialindex / libspatialite** | various | Spatial indexing for sections / polygons |
| **opencv** | 4.5.4 | Vision (See & Spray / camera path) |
| **apriltag** | 3.2.0 | Visual fiducial / calibration |
| **FreeRTOS** | V10.x, V202112 | **Implement ECU RTOS** (MNC, SRC, NZC class devices) |
| **Infineon-iLLD** / **XMClib** | various | **AURIX / XMC** MCU drivers — typical JD ECU silicon |
| **TI-Runtime Support Library** | v5.2.11, v6.2.0 | **TI C2000** class controllers (sprayer/rate path) |
| **xilinx-embeddedsw / MicroBlaze** | 2013–2019 | **FPGA** in premium/server or vision pipeline |
| **libnl** | 3.2.25 | Netlink — Linux CAN/socket routing on display board |
| **iperf** | 2.1.9 | Ethernet bench bandwidth |
| **arp-scan** | 1.7 | Discover display / service port on local subnet |
| **avahi** | 0.8 | mDNS — find display or service hostname on LAN |

---

## Tier B — Display / DISP decode context (what we see on CAN from `0xF0` / `0x26`)

| Package | Version(s) | Notes |
| :--- | :--- | :--- |
| **linux-windriver** | 4.1 | **Wind River Linux** on display board services |
| **platform-setup-eurotech** | 1.0 | **Eurotech** compute module for CommandCenter |
| **packagegroup-wr-base** | 1.0 | Yocto/WR base image |
| **matchbox-wm / matchbox-terminal** | 1.2 / 0.0 | Embedded **window manager** — VT UI shell |
| **xserver-xorg** | 1.18.1 | X11 display server |
| **wayland / weston** | 1.17.0 / 1.8.0 | Alternate compositor path |
| **aspnetcore-runtime** | 8.0.6-linux-x64 | **.NET 8** — major application layer on 4600 |
| **mono** | 6.4.0 | Legacy .NET / mixed runtime |
| **python** / **python3** | 2.7.9 / 3.4.3 | Scripting on display (older; app may bundle newer) |
| **numpy / pandas / matplotlib / scipy / scikit-learn** | various | On-display **analytics** — rate maps, yield-style UI |
| **gstreamer** (+ plugins) | 1.12.2 | Media / camera pipelines |
| **LibVNCServer** | 0.9.14 | Remote display / service access |
| **libwebsockets** | 1.3 | Web-style local APIs |
| **log4cplus** | 2.1.0 | Structured logging — correlate with service logs if ever available |

**CAN link:** DISP EF00 `F107CC` / `F002CC` / `F10FFF` (~10 Hz) are **rebroadcast/liveness**, not GIS. Heavy geometry stays on display; bus carries summaries + TC process data.

---

## Tier C — Infrastructure (background only)

Security: openssl (multiple), mbedtls, gnupg, gpgme, gnutls, nettle, libsodium, openssh, sudo, snoopy.  
Boot/storage: syslinux, mtd-utils, e2fsprogs (if present), xz, zlib, lz4.  
Init/package: sysvinit, opkg, yum, rpm, opkg-utils.  
Shell/utils: bash, coreutils-class (util-linux, procps, grep, sed, tar, vim, less).  
Wireless: wl18xx-fw, wpa-supplicant, wireless-tools, rfkill.  
Time: ntp, tzdata, pytz, python-dateutil.  
Audio: pulseaudio, speexdsp.  
Fonts/UI: freetype, fontconfig, pango, cairo-class deps, ncurses.

---

## Full inventory by appendix section

### Board Services (embedded Linux base)

```
jpeg-9a, json-c-0.12, kbd-2.0.2, kexec-tools-2.0.10, kmod-21, less-479,
libarchive-3.1.2, libassuan-2.2.1, libcap-2.24, libdaemon-0.14, libdmx-1.1.1.3,
libdrm-2.4.67, libepoxy-1.3.1, libevdev-1.4.2, libevent-2.0.22, libfakekey-0.0,
libffi-3.2.1, libfontenc-1.1.1.3, libgcrypt-1.6.3, libglu-2.9.0, libgpg-error-1.19,
libgssglue-0.1, libice-1.0.9, libinput-0.21.0, libmatchbox-1.11, libnewt-0.52.18,
libnl-1.3.2.25, libnss-mdns-0.10,
libxext, libxfixes, libxfont, libxft, libxi, libxinerama, libxkbcommon, libxkbfile,
libxkbui, libxklavier, libxml2, libxmu, libxpm, libxrandr, libxrender, libxres,
libxsettings-client, libxslt, libxt, libxtst, libxv, libxvmc, libxxf86dga, libxxf86misc, libxxf86vm,
linux-firmware-1.0.0, linux-windriver-4.1, lmsensors-3.4.0, logrotate-3.9.1, lsof-4.89,
lttng-tools-2.6.0, lttng-ust-2.6.2, m4-1.4.9, matchbox-keyboard-0.0, matchbox-terminal-0.0,
matchbox-wm-1.2, mesa-11.1.2, mingetty-1.08, mkfontdir, mkfontscale, mktemp, mtd-utils-1.5.1,
mtdev-1.1.5, mtools-3.9.9, ncurses-5.9, net-tools-1.60, netbase-5.3, nettle-3.1.1,
nspr-4.21, nss-3.42.1, ntfs-3g, ntp-4.2.8p4, openssh-7.1p1, openssl-1.0.2d,
opkg, opkg-arch-config, opkg-utils, os-release, ossp-uuid-1.6.2,
packagegroup-core-boot, packagegroup-core-x11, packagegroup-core-x11-xserver, packagegroup-wr-base,
pango-1.36.8, pciutils-3.4.1, perl-5.22.0, pixman-0.32.6, platform-setup-eurotech-1.0,
pm-utils, popt, powertop, procps, psmisc, pulseaudio-6.0,
pygpgme, python-2.7.9, python3-3.4.3, python-pycurl, python-setuptools, python-smartpm,
readline, rfkill, rng-tools, rpm-5.4.14, rsync, rxvt-unicode,
sed, shadow, slang, snoopy, speexdsp, sqlite3, startup-notification, sudo,
syslogd, syslog-ng, sysstat, sysvinit, syslinux-6.03, tar, tcl, tcp-wrappers,
tcpdump-4.7.4, tiff, tinylogin, tnftp, tzdata, udev, urlgrabber,
usb-modeswitch, usbutils, util-linux, vim, vlock, vte, wayland-1.17.0, weston-1.8.0,
wireless-tools, wl18xx-fw, wpa-supplicant, wr-init, x11-common, xauth, xcb-util-*,
xdpyinfo, xf86-input-*, xf86-video-fbdev/intel/vesa, xhost, xinit, xinput, xinput-calibrator,
xkbcomp, xkeyboard-config, xmodmap, xorg-minimal-fonts, xprop, xrandr, xserver-xorg-1.18.1,
xset, xtscal, xz, yum, zlib
```

### Board Services (continued — Eurotech / GL)

```
eurotech-bios-password, eurotech-versions-*, eventlog, expat, fbset, file, findutils,
fontconfig, fpga-1.0, freetype, fuse, gawk, gcc-source, gdbm, gdk-pixbuf, glew, glib, glibc,
gmp, gnupg, gnutls, gpgme, grep, …
```

### Application — 4600 CommandCenter / 4640 Universal Display

```
actc-1.1, aenum-2.2.3, amazon-kinesis-video-streams-producer-sdk-cpp-3.3.1,
amazon-kinesis-video-streams-webrtc-sdk-c-1.7.3, apriltag-3.2.0, arp-scan-1.7,
aspnetcore-runtime-8.0.6-linux-x64, attrs, avahi-0.8, awsiotcppsdk-1.3.0, boost-1.56.0,
Click, cligj, cycler, enum34, Fiona-1.8.13, gdal-2.4.0, gdb, GeographicLib-2.3, geos-3.7.1,
glm, gstreamer-1.12.2 (+ plugins), h3-4.0.1, iniparse, intel-vaapi-driver, iperf-2.1.9,
kiwisolver, libdatrie, libfaketime, libgdiplus, libgooglepinyin, libsodium,
libspatialite-4.3.0, libsqlite3-3.45.01, libsrtp, libthai, libva, LibVNCServer-0.9.14,
libwebsockets-1.3, libxml2-python3, log4cplus, lua-5.3, lxml, lz4,
matplotlib-2.2.5, mbedtls, mono-6.4.0, mosquitto-2.0.14/2.0.21, munch, nocache, nose,
numpy-1.15.4, opencv-4.5.4, openh264, openssl-1.1.1, orc, pandas-0.24.2, poly2tri,
postgresql-protobuf-2.6.0, proj-5.0.0, protobuf-2.5.0/3.18.3, protobuf-c-1.2.1,
ps_mem, pyftpdlib, pyproj, python-bcolz, python-dateutil, python-geopandas-0.6.3,
python-paho-mqtt-1.5.0, python-pyparsing, python-rtree, python-six, python-subprocess32,
python-utm-0.5.0, pytz, qterminal, qtermwidget, quazip, rapidjson-1.1.0, rust-0.1.0,
scikit-learn-0.20.4, scipy-1.2.3, shapelib-1.4.1, Shapely-1.7.0, sol2, spatialindex,
usrsctp-0.9.5.0
```

### Installed Features — machine / implement ECUs

```
FreeRTOS-Kernel V10.1.1, V10.4.2, V10.4.3, V10.4.6, V202112.00,
Infineon-iLLD-1.0.1.12.0, Infineon-iLLD-1.0.1.13.0,
libpcap-1.0.0, libsodium-1.0.17,
lwIP-2.0.3, lwIP-2.1.0,
mbedtls-2.16.3, nanopb-0.3.9,
TI-Runtime Support Library v5.2.11, v6.2.0,
WinPcap-4.0,
xilinx-embeddedsw v2013.2, v2015.1, v2016.2, v2019.2,
Xilinx-MicroBlaze 2013.05.15 – 2019.04.01,
XMClib-v2.1.6
```

---

## Project takeaways

1. **CAN X119 tap remains the right layer** for live rate/section/MNC — display runs GIS, MQTT, AWS, and .NET; that logic does not need to appear on implement CAN.
2. **nanopb/protobuf** — if a proprietary PGN payload looks structured but not J1939, try protobuf/nanopb schemas before assuming encryption.
3. **json-c / rapidjson** — internal and export paths may mirror our JSON library files (`section_map.json`, `disp_catalog.json`).
4. **Eurotech + Wind River Linux** — display is a rugged embedded PC; **FreeRTOS + lwIP + Infineon/TI** — implement nodes.
5. **tcpdump/libpcap** — future option on **vehicle Ethernet** (VB1), not a substitute for COM2 CAN sniff.
6. **OpenCV + Kinesis + apriltag** — See & Spray vision is display/cloud adjacent; PUFVision vision stays separate on laptop.

---

## Related PUFworks files

| File | Role |
| :--- | :--- |
| `library/disp_catalog.json` | DISP CAN prefix decode (field) |
| `library/SPRAY_DECODE.md` | Human CAN decode ledger |
| `library/spray_pgn_library.json` | Recorder PGN filter |

**Do not expect** this appendix to list ISOBUS stack names (often proprietary JD builds). It documents **third-party** deps only.
