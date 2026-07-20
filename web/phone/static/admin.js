(function () {
  const NODE_KEYS = [
    ["gwc_alive", "GWC"],
    ["src_alive", "SRC"],
    ["mnc_alive", "MNC"],
    ["bhc_alive", "BHC"],
    ["atx_alive", "ATX"],
    ["grc_alive", "GRC"],
  ];

  const FIX_LABELS = {
    0: "Invalid",
    1: "GPS",
    2: "DGPS",
    4: "RTK fixed",
    5: "RTK float",
  };

  const el = (id) => document.getElementById(id);
  let pollTimer = null;
  let pollMs = 500;
  let polls = 0;
  let lastPoll = performance.now();
  let configLoaded = false;

  function fmtNum(v, d) {
    if (v == null || Number.isNaN(v)) return "—";
    return Number(v).toFixed(d);
  }

  function setConn(live) {
    const pill = el("conn-pill");
    if (live) {
      pill.className = "pill pill-ok";
      pill.textContent = "Live";
    } else {
      pill.className = "pill pill-bad";
      pill.textContent = "Stale";
    }
  }

  function setStatus(msg, ok) {
    el("status-msg").textContent = msg;
    el("status-msg").className = ok === false ? "bad" : "";
  }

  async function apiGet(path) {
    const r = await fetch(path, { cache: "no-store" });
    return r.json();
  }

  async function apiPost(path, body) {
    const r = await fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    return r.json();
  }

  function readForm(formId, fields) {
    const out = {};
    fields.forEach(function (name) {
      const node = el(name);
      if (!node) return;
      let v = node.value;
      if (name === "nmea_relay") v = v === "true";
      if (["udp_port", "nmea_udp_port", "can_bitrate", "tty_baud", "can_rx_max_hz"].includes(name))
        v = parseInt(v, 10);
      if (name === "can_interface") {
        const custom = el("can_interface_custom").value.trim();
        v = custom || v;
      }
      out[name] = v;
    });
    return out;
  }

  function fillForm(cfg) {
    const set = (id, val) => {
      const n = el(id);
      if (n) n.value = val == null ? "" : String(val);
    };
    set("can_bitrate", cfg.can_bitrate || 250000);
    set("tty_baud", cfg.tty_baud || 115200);
    set("sprayer_profile", cfg.sprayer_profile || "jd_616r");
    set("sniff_mode", cfg.sniff_mode || "616r");
    set("udp_port", cfg.udp_port || 5578);
    set("multicast_group", cfg.multicast_group || "239.255.42.1");
    set("unicast_client", cfg.unicast_client || "");
    set("nmea_relay", cfg.nmea_relay !== false ? "true" : "false");
    set("nmea_udp_port", cfg.nmea_udp_port || 9999);
    set("can_rx_max_hz", cfg.can_rx_max_hz != null ? cfg.can_rx_max_hz : 50);
    pollMs = cfg.ui_poll_ms || parseInt(localStorage.getItem("ui_poll_ms") || "500", 10);
    set("ui_poll_ms", pollMs);

    const sel = el("can_interface");
    const ports = window._comPorts || [];
    sel.innerHTML = "";
    ports.forEach(function (p) {
      const o = document.createElement("option");
      o.value = p;
      o.textContent = p;
      sel.appendChild(o);
    });
    const iface = cfg.can_interface || "COM2";
    if (ports.includes(iface)) {
      sel.value = iface;
      el("can_interface_custom").value = "";
    } else {
      el("can_interface_custom").value = iface;
    }
  }

  async function loadConfig() {
    try {
      const data = await apiGet("/api/config");
      window._comPorts = data.com_ports || [];
      fillForm(data.config || {});
      if (data.lan_ip) {
        el("lan-ip").textContent = data.lan_ip;
        el("dash-url").textContent = "http://" + data.lan_ip + ":8080/";
      }
      configLoaded = true;
    } catch (e) {
      setStatus("Config load failed", false);
    }
  }

  function renderNodes(t) {
    const box = el("nodes");
    box.innerHTML = "";
    NODE_KEYS.forEach(function ([key, label]) {
      const on = !!t[key];
      const div = document.createElement("div");
      div.className = "node";
      div.innerHTML =
        '<div class="node-dot ' + (on ? "on" : "off") + '"></div>' +
        '<div class="node-lbl">' + label + "</div>";
      box.appendChild(div);
    });
  }

  function renderGps(gps, tel, snap) {
    const valid = gps && gps.valid;
    const live = snap.gps_live;
    const pill = el("gps-fix-pill");
    if (valid && live) {
      pill.className = "pill pill-ok";
      pill.textContent = FIX_LABELS[gps.fix_quality] || "Fix";
    } else if (gps && gps.latitude != null && !live) {
      pill.className = "pill pill-warn";
      pill.textContent = "Stale";
    } else {
      pill.className = "pill pill-bad";
      pill.textContent = tel && tel.atx_alive ? "Waiting GPS" : "No ATX";
    }
    if (gps && gps.latitude != null) {
      el("gps-coords").textContent =
        fmtNum(gps.latitude, 6) + ", " + fmtNum(gps.longitude, 6);
    } else {
      el("gps-coords").textContent = "—";
    }
    el("gps-speed").textContent =
      gps && gps.speed_kmh != null ? fmtNum(gps.speed_kmh, 1) + " km/h" : "—";
    el("gps-heading").textContent =
      gps && gps.heading_deg != null ? fmtNum(gps.heading_deg, 1) + "°" : "—";
    el("gps-sats").textContent =
      gps && gps.satellites != null ? gps.satellites : "—";
    el("gps-quality").textContent =
      gps && gps.fix_quality != null
        ? (FIX_LABELS[gps.fix_quality] || gps.fix_quality)
        : "—";
    el("gps-atx").textContent = tel && tel.atx_alive ? "Alive" : "—";
    el("gps-nmea").textContent = snap.stats ? snap.stats.nmea_sent || 0 : "—";
  }

  function renderLogs(logs) {
    const box = el("logs");
    if (!logs || !logs.length) {
      box.innerHTML = '<div class="log-line">—</div>';
      return;
    }
    box.innerHTML = logs
      .slice(0, 30)
      .map(function (l) {
        return '<div class="log-line">' + escapeHtml(l.line || "") + "</div>";
      })
      .join("");
  }

  function escapeHtml(s) {
    return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }

  async function poll() {
    try {
      const snap = await apiGet("/api/snapshot");
      const t = snap.telemetry || {};
      const gps = snap.gps || {};
      setConn(!!snap.telemetry_live);
      renderGps(gps, t, snap);
      renderNodes(t);
      renderLogs(snap.logs);
      el("live-can").textContent = t.can_status || "—";
      el("live-if").textContent = t.can_interface || snap.hub?.can_interface || "—";
      el("live-speed").textContent = fmtNum(t.speed_kmh, 1) + " km/h";
      el("live-auth").textContent = t.control_authority || "—";
      el("live-can-age").textContent =
        snap.can_rx_age_s != null ? snap.can_rx_age_s + " s" : "—";
      el("live-tel").textContent = snap.telemetry_live ? "Live" : "Stale";
      el("live-stats").textContent = snap.stats
        ? "tel " + snap.stats.telemetry + " · rx " + snap.stats.can_rx
        : "—";
      el("live-uptime").textContent = (snap.uptime_s || 0) + " s";
      el("can-status-line").textContent =
        "CAN: " + (t.can_status || "?") + " · " + (t.can_error_msg || "OK");
      polls += 1;
      const now = performance.now();
      if (polls > 2) {
        el("poll-hz").textContent = (1000 / ((now - lastPoll) / polls)).toFixed(1) + " Hz";
      }
    } catch (e) {
      setConn(false);
      el("conn-pill").textContent = "Offline";
    }
  }

  function schedulePoll() {
    if (pollTimer) clearInterval(pollTimer);
    pollTimer = setInterval(poll, pollMs);
  }

  const CAN_FIELDS = [
    "can_interface",
    "can_bitrate",
    "tty_baud",
    "sprayer_profile",
    "sniff_mode",
  ];
  const NET_FIELDS = [
    "udp_port",
    "multicast_group",
    "unicast_client",
    "nmea_relay",
    "nmea_udp_port",
    "can_rx_max_hz",
    "ui_poll_ms",
  ];

  el("btn-save-can").addEventListener("click", async function () {
    const patch = readForm("form-can", CAN_FIELDS);
    setStatus("Saving CAN…");
    const res = await apiPost("/api/config", { config: patch });
    if (!res.ok) {
      setStatus(res.message || "Save failed", false);
      return;
    }
    const apply = await apiPost("/api/can/apply", {});
    setStatus(apply.message || res.message, apply.ok);
    fillForm(res.config || patch);
  });

  el("btn-restart-can").addEventListener("click", async function () {
    setStatus("Restarting CAN…");
    const res = await apiPost("/api/can/restart", {});
    setStatus(res.message || "Done", res.ok);
  });

  el("btn-save-net").addEventListener("click", async function () {
    const patch = readForm("form-net", NET_FIELDS);
    pollMs = patch.ui_poll_ms || 500;
    localStorage.setItem("ui_poll_ms", String(pollMs));
    delete patch.ui_poll_ms;
    setStatus("Saving network…");
    const res = await apiPost("/api/config", { config: patch });
    setStatus(res.message || "Saved", res.ok);
    if (res.config) fillForm(res.config);
    schedulePoll();
  });

  el("btn-apply-net").addEventListener("click", async function () {
    setStatus("Applying UDP + NMEA…");
    const res = await apiPost("/api/network/apply", {});
    setStatus(res.message || "Done", res.ok);
  });

  el("btn-refresh").addEventListener("click", poll);

  el("log-toggle").addEventListener("click", function () {
    const sec = el("log-toggle").closest(".collapsible");
    sec.classList.toggle("hidden");
    el("log-toggle").textContent = sec.classList.contains("hidden") ? "show" : "hide";
  });

  loadConfig().then(function () {
    poll();
    schedulePoll();
  });
})();
