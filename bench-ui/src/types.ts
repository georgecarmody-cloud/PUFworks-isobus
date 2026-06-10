// Mirror of PUFworks-contracts typescript/index.ts (TelemetryV1 subset + bench extras).

export type ControlAuthority =
  | 'OBSERVE' | 'ANNOUNCE' | 'SHADOW' | 'RATE_ONLY' | 'SECTION' | 'FULL';

export const AUTHORITY_LADDER: ControlAuthority[] = [
  'OBSERVE', 'ANNOUNCE', 'SHADOW', 'RATE_ONLY', 'SECTION', 'FULL',
];

/** Rungs that can actuate hardware — require an explicit confirm gate. */
export const ACTUATION_RUNGS: ControlAuthority[] = ['RATE_ONLY', 'SECTION', 'FULL'];

export interface Telemetry {
  schema: 'TelemetryV1';
  ts_ms: number;
  control_authority: ControlAuthority;
  control_armed: boolean;
  control_interlocks?: Record<string, boolean>;
  control_demote_reason?: string | null;
  sprayer_profile?: string;
  section_bitmap?: string;
  jd_commanded_sections?: string;
  cooperative_mode?: boolean;
  speed_kmh?: number;
  target_rate_l_ha?: number;
  isobus_is_connected?: boolean;
  isobus_jdrc_address?: number;
  record_session_active?: boolean;
  record_session_id?: string | null;
  record_frame_count?: number;
  record_shadow_count?: number;
  can_status?: string;
  can_interface?: string;
  can_error_msg?: string;
  isobus_sa?: number;
  vt_handshake_state?: string;
  grc_alive?: boolean;
  grc_master_on?: boolean | null;
  grc_ef00_rate_l_ha?: number;
  grc_sections?: Record<string, boolean>;
  vision_seen?: boolean;
  vision_fresh?: boolean;
  vision_seq?: number;
  vision_source?: string;
  gs_enabled?: boolean;
  gs_port?: string;
  gs_link_state?: string;
  gs_last_rate?: number;
  gs_blank_state?: string;
  gs_boom_blanking?: boolean;
  [key: string]: unknown;
}

declare global {
  interface Window {
    benchAPI: {
      sendToEngine: (line: string) => void;
      onEngineOut: (cb: (line: string) => void) => void;
      onEngineErr: (cb: (text: string) => void) => void;
    };
  }
}
