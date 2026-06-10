import { useCallback, useEffect, useRef, useState } from 'react';
import {
  ACTUATION_RUNGS,
  AUTHORITY_LADDER,
  ControlAuthority,
  Telemetry,
} from './types';

const MAX_LOG_LINES = 400;
const MAX_CAN_LINES = 200;

export default function App() {
  const [telemetry, setTelemetry] = useState<Telemetry | null>(null);
  const [logLines, setLogLines] = useState<string[]>([]);
  const [canLines, setCanLines] = useState<string[]>([]);
  const [iface, setIface] = useState('virtual');
  const [recordLabel, setRecordLabel] = useState('');
  const [manualBitmap, setManualBitmap] = useState('0x0');
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
        setCanLines((prev) => [line.slice('CAN_RX:'.length), ...prev].slice(0, MAX_CAN_LINES));
      } else {
        setLogLines((prev) => [line, ...prev].slice(0, MAX_LOG_LINES));
      }
    });
    window.benchAPI.onEngineErr((text) => {
      setLogLines((prev) => [`[stderr] ${text}`, ...prev].slice(0, MAX_LOG_LINES));
    });
  }, []);

  // UI host obligation: UI_HEARTBEAT at 1 Hz, always-on while the window lives.
  // The engine demotes to SHADOW if this stops for >3 s (SAFETY.md).
  useEffect(() => {
    const id = setInterval(() => sendRef.current('UI_HEARTBEAT'), 1000);
    return () => clearInterval(id);
  }, []);

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
        <div className={`pill ${armed ? 'danger' : 'ok'}`}>{armed ? 'ARMED' : 'DISARMED'}</div>
        <div className="pill">{authority}</div>
      </header>

      <main>
        <section className="panel">
          <h2>Bus</h2>
          <div className="row">
            <select value={iface} onChange={(e) => setIface(e.target.value)}>
              <option value="virtual">virtual (bench)</option>
              <option value="auto">auto-scan</option>
              <option value="pcan">PCAN</option>
              <option value="ixxat">IXXAT</option>
              <option value="can0">can0</option>
            </select>
            <button onClick={() => { send(`SET_CAN_INTERFACE:${iface}`); }}>Set interface</button>
            <button onClick={() => send('START_CAN')}>Start CAN</button>
            <button onClick={() => send('STOP_CAN')}>Stop CAN</button>
            <button onClick={() => send('RECLAIM_ADDRESS')}>Reclaim SA</button>
          </div>
          <div className="kv">
            <span>SA</span><b>{t?.isobus_sa != null ? `0x${t.isobus_sa.toString(16).toUpperCase()}` : '—'}</b>
            <span>VT</span><b>{t?.vt_handshake_state ?? '—'}</b>
            <span>Speed</span><b>{t?.speed_kmh?.toFixed(1) ?? '—'} km/h</b>
            <span>Profile</span><b>{t?.sprayer_profile ?? '—'}</b>
          </div>
          <div className="row">
            <label>Profile</label>
            {['goldacres_grc', 'jd_616r', 'generic'].map((p) => (
              <button key={p}
                className={t?.sprayer_profile === p ? 'active' : ''}
                onClick={() => send(`SET_SPRAYER_PROFILE:${p}`)}>{p}</button>
            ))}
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
          <div className="kv">
            {Object.entries(interlocks).map(([k, v]) => (
              <span key={k} className={`pill ${v ? 'ok' : 'danger'}`}>{k}: {v ? 'OK' : 'TRIP'}</span>
            ))}
          </div>
          {t?.control_demote_reason ? (
            <div className="demote">Last demote: {t.control_demote_reason}</div>
          ) : null}
        </section>

        <section className="panel">
          <h2>Sections / Vision feed</h2>
          <div className="kv">
            <span>Bitmap</span><b>{t?.section_bitmap ?? '—'}</b>
            <span>Host AND-gate</span><b>{t?.jd_commanded_sections ?? '—'}</b>
            <span>Vision</span>
            <b className={t?.vision_seen ? (t?.vision_fresh ? 'ok-text' : 'danger-text') : ''}>
              {t?.vision_seen ? (t?.vision_fresh ? `fresh (${t?.vision_source})` : 'STALE — closed') : 'no feed'}
            </b>
          </div>
          <div className="row">
            <input value={manualBitmap} onChange={(e) => setManualBitmap(e.target.value)}
              placeholder="0x1F" />
            <button onClick={() => send(`SET_SECTION_BITMAP:${manualBitmap}`)}>Bench vector</button>
            <button onClick={() => send('TEST_BOOM_SECTIONS:1')}>All ON (flush)</button>
            <button onClick={() => send('TEST_BOOM_SECTIONS:0')}>All OFF</button>
          </div>
        </section>

        <section className="panel">
          <h2>Recorder (OBSERVE–SHADOW)</h2>
          <div className="row">
            <input value={recordLabel} onChange={(e) => setRecordLabel(e.target.value)}
              placeholder="session label" />
            <button disabled={t?.record_session_active === true}
              onClick={() => send(recordLabel ? `START_RECORD_SESSION:${recordLabel}` : 'START_RECORD_SESSION')}>
              Start
            </button>
            <button disabled={t?.record_session_active !== true}
              onClick={() => send('STOP_RECORD_SESSION')}>Stop</button>
          </div>
          <div className="kv">
            <span>Session</span><b>{t?.record_session_id ?? '—'}</b>
            <span>Frames</span><b>{t?.record_frame_count ?? 0}</b>
            <span>Shadow rows</span><b>{t?.record_shadow_count ?? 0}</b>
          </div>
        </section>

        <section className="panel">
          <h2>GreenSeeker (616R)</h2>
          <div className="row">
            <button onClick={() => send(`SET_GS_EMITTER:${t?.gs_enabled ? 0 : 1}`)}>
              {t?.gs_enabled ? 'Disable' : 'Enable'} emitter
            </button>
            <button onClick={() => send(`SET_GS_BLANKING:${t?.gs_boom_blanking ? 0 : 1}`)}>
              {t?.gs_boom_blanking ? 'Blanking OFF' : 'Blanking ON'}
            </button>
          </div>
          <div className="kv">
            <span>Link</span><b>{String(t?.gs_link_state ?? '—')}</b>
            <span>Port</span><b>{String(t?.gs_port ?? '—')}</b>
            <span>Last rate</span><b>{t?.gs_last_rate ?? '—'} L/ha</b>
            <span>Blank</span><b>{String(t?.gs_blank_state ?? '—')}</b>
          </div>
        </section>

        <section className="panel wide">
          <h2>Engine log</h2>
          <pre className="log">{logLines.join('\n')}</pre>
        </section>

        <section className="panel wide">
          <h2>CAN RX</h2>
          <pre className="log can">{canLines.join('\n')}</pre>
        </section>
      </main>
    </div>
  );
}
