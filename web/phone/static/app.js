(function () {
  const NODE_KEYS = [
    ["gwc_alive", "GWC"],
    ["src_alive", "SRC"],
    ["mnc_alive", "MNC"],
    ["bhc_alive", "BHC"],
    ["atx_alive", "ATX"],
    ["grc_alive", "GRC"],
  ];

  const el = (id) => document.getElementById(id);
  let polls = 0;
  let lastPoll = performance.now();

  function fmtSpeed(v) {
    if (v == null || Number.isNaN(v)) return "—";
    return Number(v).toFixed(1);
  }

  function renderNodes(t) {
    const box = el("nodes");
    box.innerHTML = "";
    NODE_KEYS.forEach(([key, label]) => {
      const on = !!t[key];
      const div = document.createElement("div");
      div.className = "node";
      div.innerHTML =
        '<div class="node-dot ' + (on ? "on" : "off") + '"></div>' +
        '<div class="node-lbl">' + label + "</div>";
      box.appendChild(div);
    });
  }

  function renderFrames(frames) {
    const box = el("frames");
    if (!frames || !frames.length) {
      box.className = "frames empty";
      box.textContent = "No spray frames yet";
      return;
    }
    box.className = "frames";
    box.innerHTML = frames
      .slice(0, 20)
      .map(function (f) {
        return (
          '<div class="frame-row">' +
          '<span class="frame-sa">' + (f.sa_label || f.sa_hex || "?") + "</span>" +
          '<span class="frame-pgn">' + (f.pgn_hex || "") + "</span>" +
          '<span class="frame-name">' + (f.pgn_name || f.category || "") + "</span>" +
          "</div>"
        );
      })
      .join("");
  }

  function renderLogs(logs) {
    const box = el("logs");
    if (!logs || !logs.length) {
      box.innerHTML = '<div class="log-line">—</div>';
      return;
    }
    box.innerHTML = logs
      .slice(0, 15)
      .map(function (l) {
        return '<div class="log-line">' + escapeHtml(l.line || "") + "</div>";
      })
      .join("");
  }

  function escapeHtml(s) {
    return s
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;");
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

  async function poll() {
    try {
      const r = await fetch("/api/snapshot", { cache: "no-store" });
      const snap = await r.json();
      const t = snap.telemetry || {};
      el("speed").textContent = fmtSpeed(t.speed_kmh);
      const gps = snap.gps || {};
      if (gps.valid && snap.gps_live) {
        el("gps-line").textContent =
          Number(gps.latitude).toFixed(5) + ", " + Number(gps.longitude).toFixed(5);
      } else if (gps.latitude != null) {
        el("gps-line").textContent = "Stale";
      } else {
        el("gps-line").textContent = t.atx_alive ? "Waiting…" : "No ATX";
      }
      el("can-status").textContent = t.can_status || "—";
      el("profile").textContent = t.sprayer_profile || "—";
      el("authority").textContent = t.control_authority || "—";
      el("sections").textContent = t.section_bitmap || "—";
      renderNodes(t);
      renderFrames(snap.frames);
      renderLogs(snap.logs);
      setConn(!!snap.telemetry_live);
      el("uptime").textContent = "up " + (snap.uptime_s || 0) + "s";
      polls += 1;
      const now = performance.now();
      if (polls > 3) {
        const hz = (1000 / ((now - lastPoll) / polls)).toFixed(1);
        el("poll-hz").textContent = hz + " Hz";
      }
    } catch (e) {
      setConn(false);
      el("conn-pill").textContent = "Offline";
    }
  }

  el("log-toggle").addEventListener("click", function () {
    const sec = el("log-toggle").closest(".collapsible");
    sec.classList.toggle("hidden");
    el("log-toggle").textContent = sec.classList.contains("hidden") ? "show" : "hide";
  });

  poll();
  setInterval(poll, 500);
})();
