import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  ACTUATION_RUNGS,
  AUTHORITY_LADDER,
  ControlAuthority,
  Telemetry,
} from './types';
import { downloadCsv, ExportFrame, framesToCsv } from './exportFrames';
import {
  frameInSprayLibrary,
  isUiNoise,
  pgnMeta,
  SPRAY_CATEGORIES,
  SprayCategory,
} from './sprayFilter';

const MAX_LOG_LINES = 400;
const MAX_CAN_FRAMES = 600;

interface CanFrame extends ExportFrame {
  pf: number;
}

function parseCanLine(json: string): CanFrame | null {
  try {
    const raw = JSON.parse(json);
    const id = parseInt(raw.id, 16);
    const pf = (id >> 16) & 0xff;
    const ps = (id >> 8) & 0xff;
    const sa = id & 0xff;
    const da = pf < 240 ? ps : 0xff;
    const pgn = pf < 240 ? pf << 8 : (pf << 8) | ps;
    const meta = pgnMeta(pgn);
    return {
      t: Date.now(),
      id,
      sa,
      da,
      pf,
      pgn,
      dlc: raw.dlc ?? 0,
      data: raw.data ?? '',
      pgnName: meta.name,
      category: meta.category,
      saLabel: '',
    };
  } catch {
    return null;
  }
}

function parseCsvHex(text: string): number[] {
  return text
    .split(',')
    .map((s) => s.trim())
    .filter(Boolean)
    .map((s) => parseInt(s, 16))
    .filter((n) => !Number.isNaN(n));
}

const hex = (n: number, w = 2) => `0x${n.toString(16).toUpperCase().padStart(w, '0')}`;

const fmtTime = (ms: number) => {
  const d = new Date(ms);
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}:` +
    `${String(d.getSeconds()).padStart(2, '0')}.${String(d.getMilliseconds()).padStart(3, '0')}`;
};

export default function App() {
  const [telemetry, setTelemetry] = useState<Telemetry | null>(null);
  const [logLines, setLogLines] = useState<string[]>([]);
  const [canFrames, setCanFrames] = useState<CanFrame[]>([]);
  const [iface, setIface] = useState(() => localStorage.getItem('bench.iface') ?? 'virtual');
  const [recordLabel, setRecordLabel] = useState('');
  const [sniffMode, setSniffMode] = useState<'filtered' | 'spray' | '616r' | '616r_full'>('spray');
  const [manualBitmap, setManualBitmap] = useState('0x0');
  const [simSpeed, setSimSpeed] = useState('5');

  // CAN monitor — spray library preset (default on)
  const [sprayLibraryOnly, setSprayLibraryOnly] = useState(true);
  const [hideUiNoise, setHideUiNoise] = useState(true);
  const [enabledCats, setEnabledCats] = useState<Set<SprayCategory>>(
    () => new Set(SPRAY_CATEGORIES.map((c) => c.id)),
  );
  const [onlySa, setOnlySa] = useState('');
  const [paused, setPaused] = useState(false);
  const pausedRef = useRef(paused);
  pausedRef.current = paused;

  const sendRef = useRef<(line: string) => void>(() => {});
  const send = useCallback((line: string) => {
    window.benchAPI.sendToEngine(line);
  }, []);
  sendRef.current = send;

  // Engine output pump
  useEffect(() => {
    window.benchAPI.onEngineOut((line) => {
      if (line.startsWith('TELEMETRY:')) {
        try {
          setTelemetry(JSON.parse(line.slice('TELEMETRY:'.length)));
        } catch {
          /* partial line — skip */
        }
      } else if (line.startsWith('CAN_RX:')) {
        if (pausedRef.current) return;
        const frame = parseCanLine(line.slice('CAN_RX:'.length));
        if (frame) {
          setCanFrames((prev) => [frame, ...prev].slice(0, MAX_CAN_FRAMES));
        }
      } else {
        setLogLines((prev) => [line, ...prev].slice(0, MAX_LOG_LINES));
      }
    });
    window.benchAPI.onEngineErr((text) => {
      setLogLines((prev) => [`[stderr] ${text}`, ...prev].slice(0, MAX_LOG_LINES));
    });
  }, []);

  // UI host obligation: UI_HEARTBEAT at 1 Hz, always-on while the window lives.
  useEffect(() => {
    const id = setInterval(() => sendRef.current('UI_HEARTBEAT'), 1000);
    return () => clearInterval(id);
  }, []);

  useEffect(() => {
    localStorage.setItem('bench.iface', iface);
  }, [iface]);

  const setAuthority = (rung: ControlAuthority) => {
    if (ACTUATION_RUNGS.includes(rung)) {
      const ok = window.confirm(
        `Raise control authority to ${rung}?\n\n` +
        'This rung permits CAN transmission to the sprayer when ARMed. ' +
        'Confirm the machine is in a safe state.',
      );
      if (!ok) return;
    }
    send(`SET_CONTROL_AUTHORITY:${rung}`);
  };

  const arm = () => {
    const ok = window.confirm(
      'ARM actuation?\n\nRate/section commands will be transmitted on the bus ' +
      'at the current authority rung.',
    );
    if (ok) send('ARM');
  };

  /** Field sniff bring-up: COM/slcan -> RX-only seal -> OBSERVE -> START_CAN. */
  const fieldSniffStart = () => {
    send('SET_CAN_RX_ONLY:1');
    send('SET_GS_EMITTER:0');
    send(`SET_CAN_INTERFACE:${iface}`);
    send('SET_SPRAYER_PROFILE:jd_616r');
    send('SET_SNIFF_MODE:spray');
    setTimeout(() => send('SET_CONTROL_AUTHORITY:OBSERVE'), 150);
    setTimeout(() => send('START_CAN'), 400);
  };

  /** Bench bring-up (virtual bus only): interface -> START_CAN -> SHADOW. */
  const benchStart = () => {
    send(`SET_CAN_INTERFACE:${iface}`);
    setTimeout(() => send('START_CAN'), 200);
    setTimeout(() => send('SET_CONTROL_AUTHORITY:SHADOW'), 700);
  };

  const visibleFrames = useMemo(() => {
    const only = parseCsvHex(onlySa);
    return canFrames.filter((f) => {
      if (hideUiNoise && isUiNoise(f.pgn, f.sa, f.da)) return false;
      if (sprayLibraryOnly && !frameInSprayLibrary(f.pgn, f.sa, f.pf)) return false;
      if (!enabledCats.has(f.category)) return false;
      if (only.length && !only.includes(f.sa)) return false;
      return true;
    });
  }, [canFrames, sprayLibraryOnly, hideUiNoise, enabledCats, onlySa]);

  const toggleCategory = (cat: SprayCategory) => {
    setEnabledCats((prev) => {
      const next = new Set(prev);
      if (next.has(cat)) next.delete(cat);
      else next.add(cat);
      return next;
    });
  };

  const exportCsv = () => {
    const stamp = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19);
    const label = t?.record_session_id ?? 'monitor';
    downloadCsv(`spray_frames_${label}_${stamp}.csv`, framesToCsv(visibleFrames));
  };

  const t = telemetry;
  const authority = t?.control_authority ?? 'OBSERVE';
  const armed = t?.control_armed ?? false;
  const interlocks = t?.control_interlocks ?? {};

  return (
    <div className="shell">
      <header>
        <h1>PUFworks ISOBUS Bench</h1>
        <div className={`pill ${t?.isobus_is_connected ? 'ok' : 'warn'}`}>
          {t?.can_status ?? 'no engine'} {t?.can_interface ? `(${t.can_interface})` : ''}
        </div>
        <div className="pill">{t?.sprayer_profile ?? '—'}</div>
        <div className={`pill ${armed ? 'danger' : 'ok'}`}>{armed ? 'ARMED' : 'DISARMED'}</div>
        <div className="pill authority">{authority}</div>
      </header>

      {/* Always-visible safety/state strip */}
      <div className="statusbar">
        {Object.entries(interlocks).map(([k, v]) => (
          <span key={k} className={`pill ${v ? 'ok' : 'danger'}`}>{k}: {v ? 'OK' : 'TRIP'}</span>
        ))}
        <span className="pill">sections {t?.section_bitmap ?? '—'}</span>
        <span className="pill">host-gate {t?.jd_commanded_sections ?? '—'}</span>
        <span className={`pill ${t?.vision_seen ? (t?.vision_fresh ? 'ok' : 'danger') : ''}`}>
          vision {t?.vision_seen ? (t?.vision_fresh ? 'fresh' : 'STALE') : 'none'}
        </span>
        <span className="pill">{t?.speed_kmh?.toFixed(1) ?? '—'} km/h</span>
        <span className="pill" title="Frames actually transmitted per category (post-gate)">
          TX sec {t?.tx_counts?.section ?? 0} · rate {t?.tx_counts?.rate ?? 0} · claim {t?.tx_counts?.claim ?? 0}
        </span>
        {t?.can_rx_only ? (
          <span className="pill ok">RX-ONLY sealed</span>
        ) : null}
        {t?.record_session_active ? (
          <span className="pill danger">● REC {t?.record_session_id} ({t?.record_frame_count})</span>
        ) : null}
        {t?.control_demote_reason ? (
          <span className="pill warn">demoted: {t.control_demote_reason}</span>
        ) : null}
      </div>

      <main className="cols">
        <div className="sidebar">
          <section className="panel">
            <h2>Bus</h2>
            <div className="row">
              <select value={iface} onChange={(e) => setIface(e.target.value)}>
                <option value="virtual">virtual (bench)</option>
                <option value="COM2">COM2 (CANable slcan)</option>
                <option value="auto">auto-scan</option>
                <option value="pcan">PCAN</option>
                <option value="ixxat">IXXAT</option>
                <option value="can0">can0</option>
              </select>
              <button className="primary" onClick={fieldSniffStart}>Field sniff → OBSERVE</button>
              <button onClick={benchStart}>Bench → SHADOW</button>
            </div>
            <div className="row">
              <button onClick={() => send('START_CAN')}>Start</button>
              <button onClick={() => send('STOP_CAN')}>Stop</button>
              <button onClick={() => send('RECLAIM_ADDRESS')}>Reclaim SA</button>
            </div>
            <div className="row">
              {['goldacres_grc', 'jd_616r', 'generic'].map((p) => (
                <button key={p}
                  className={t?.sprayer_profile === p ? 'active' : ''}
                  onClick={() => send(`SET_SPRAYER_PROFILE:${p}`)}>{p.replace('_', ' ')}</button>
              ))}
            </div>
            <div className="kv">
              <span>SA</span><b>{t?.isobus_sa != null ? hex(t.isobus_sa) : '—'}</b>
              <span>VT</span><b>{t?.vt_handshake_state ?? '—'}</b>
            </div>
          </section>

          <section className="panel">
            <h2>Control Authority</h2>
            <div className="ladder">
              {AUTHORITY_LADDER.map((rung) => (
                <button key={rung}
                  className={`rung ${authority === rung ? 'active' : ''} ${ACTUATION_RUNGS.includes(rung) ? 'hot' : ''}`}
                  onClick={() => setAuthority(rung)}>
                  {rung}
                </button>
              ))}
            </div>
            <div className="row">
              <button className="danger" disabled={armed} onClick={arm}>ARM</button>
              <button disabled={!armed} onClick={() => send('DISARM')}>DISARM</button>
            </div>
          </section>

          <section className="panel">
            <h2>Sections</h2>
            <div className="row">
              <input value={manualBitmap} onChange={(e) => setManualBitmap(e.target.value)}
                placeholder="0x1F" />
              <button onClick={() => send(`SET_SECTION_BITMAP:${manualBitmap}`)}>Vector</button>
            </div>
            <div className="row">
              <button onClick={() => send('TEST_BOOM_SECTIONS:1')}>All ON (flush)</button>
              <button onClick={() => send('TEST_BOOM_SECTIONS:0')}>All OFF</button>
            </div>
          </section>

          <section className="panel">
            <h2>Recorder (OBSERVE–SHADOW)</h2>
            <div className="row">
              {(['filtered', 'spray', '616r', '616r_full'] as const).map((m) => (
                <button key={m}
                  className={sniffMode === m ? 'active' : ''}
                  onClick={() => { setSniffMode(m); send(`SET_SNIFF_MODE:${m}`); }}>
                  {m}
                </button>
              ))}
            </div>
            <div className="row">
              <input value={recordLabel} onChange={(e) => setRecordLabel(e.target.value)}
                placeholder="session label" />
            </div>
            <div className="row">
              <button disabled={t?.record_session_active === true}
                onClick={() => send(recordLabel ? `START_RECORD_SESSION:${recordLabel}` : 'START_RECORD_SESSION')}>
                ● Start
              </button>
              <button disabled={t?.record_session_active !== true}
                onClick={() => send('STOP_RECORD_SESSION')}>■ Stop</button>
              <b>{t?.record_shadow_count ?? 0} shadow rows</b>
            </div>
          </section>

          {t?.sprayer_profile === 'jd_616r' ? (
            <section className="panel">
              <h2>616R nodes (2s window)</h2>
              <div className="kv">
                {(['gwc_alive', 'src_alive', 'mnc_alive', 'bhc_alive', 'atx_alive'] as const).map((k) => (
                  <span key={k}>{k.replace('_alive', '').toUpperCase()}</span>
                ))}
                {(['gwc_alive', 'src_alive', 'mnc_alive', 'bhc_alive', 'atx_alive'] as const).map((k) => (
                  <b key={`${k}-v`} className={t?.[k] ? 'ok-text' : ''}>{t?.[k] ? 'alive' : '—'}</b>
                ))}
                <span>sniff</span><b>{String(t?.sniff_mode ?? sniffMode)}</b>
              </div>
            </section>
          ) : null}

          {t?.can_interface === 'virtual' ? (
            <section className="panel">
              <h2>Bench sim (virtual bus)</h2>
              <div className="row">
                <input value={simSpeed} onChange={(e) => setSimSpeed(e.target.value)}
                  placeholder="km/h" style={{ width: 80 }} />
                <button onClick={() => send(`SIMULATE_SPEED:${simSpeed}`)}>Set speed</button>
                <button onClick={() => send('SIMULATE_GRC_EF00:4F0101F401')}>Inject GRC rate (50 L/ha)</button>
              </div>
              <div className="row">
                <button onClick={() => send('SIMULATE_GRC_EF00:4F060101FF01')}>GRC master ON</button>
                <button onClick={() => send('SIMULATE_GRC_EF00:4F060100FF00')}>GRC master OFF</button>
              </div>
              <div className="kv">
                <span>GRC</span>
                <b className={t?.grc_alive ? 'ok-text' : ''}>
                  {t?.grc_alive ? `alive · ${t?.grc_ef00_rate_l_ha ?? 0} L/ha` : 'no signal'}
                </b>
              </div>
            </section>
          ) : null}

          <section className="panel">
            <h2>GreenSeeker (616R)</h2>
            <div className="row">
              <button onClick={() => send(`SET_GS_EMITTER:${t?.gs_enabled ? 0 : 1}`)}>
                {t?.gs_enabled ? 'Disable' : 'Enable'}
              </button>
              <button onClick={() => send(`SET_GS_BLANKING:${t?.gs_boom_blanking ? 0 : 1}`)}>
                {t?.gs_boom_blanking ? 'Blanking OFF' : 'Blanking ON'}
              </button>
            </div>
            <div className="kv">
              <span>Link</span><b>{String(t?.gs_link_state ?? '—')}</b>
              <span>Rate</span><b>{t?.gs_last_rate ?? '—'} L/ha</b>
              <span>Blank</span><b>{String(t?.gs_blank_state ?? '—')}</b>
            </div>
          </section>
        </div>

        <div className="mainarea">
          <section className="panel grow">
            <div className="panel-head">
              <h2>CAN monitor</h2>
              <label className="check">
                <input type="checkbox" checked={sprayLibraryOnly}
                  onChange={(e) => setSprayLibraryOnly(e.target.checked)} />
                Spray library only
              </label>
              <label className="check">
                <input type="checkbox" checked={hideUiNoise}
                  onChange={(e) => setHideUiNoise(e.target.checked)} />
                Hide UI noise (WSM / VT)
              </label>
              <div className="cat-toggles">
                {SPRAY_CATEGORIES.map((c) => (
                  <label key={c.id}>
                    <input type="checkbox" checked={enabledCats.has(c.id)}
                      onChange={() => toggleCategory(c.id)} />
                    {c.label}
                  </label>
                ))}
              </div>
              <input className="filter" value={onlySa} onChange={(e) => setOnlySa(e.target.value)}
                placeholder="only SA: 94,17,CC" title="Comma-separated hex SAs" />
              <button className={paused ? 'active' : ''} onClick={() => setPaused(!paused)}>
                {paused ? '▶ Resume' : '❚❚ Pause'}
              </button>
              <button onClick={exportCsv} disabled={!visibleFrames.length}>Export CSV</button>
              <button onClick={() => setCanFrames([])}>Clear</button>
              <span className="count">{visibleFrames.length} shown / {canFrames.length} buffered</span>
            </div>
            <div className="can-table">
              <div className="can-row can-headrow">
                <span>time</span><span>ID</span><span>SA→DA</span><span>PGN</span><span>category</span><span>data</span>
              </div>
              {visibleFrames.map((f, i) => (
                <div className="can-row" key={`${f.t}-${i}`}>
                  <span>{fmtTime(f.t)}</span>
                  <span>{hex(f.id, 8)}</span>
                  <span>{hex(f.sa)}→{hex(f.da)}</span>
                  <span title={f.pgnName}>{hex(f.pgn, 4)}</span>
                  <span className={`cat cat-${f.category}`}>{f.category.replace('_', ' ')}</span>
                  <span className="data">{f.data}</span>
                </div>
              ))}
            </div>
          </section>

          <section className="panel">
            <h2>Engine log</h2>
            <pre className="log">{logLines.join('\n')}</pre>
          </section>
        </div>
      </main>
    </div>
  );
}
