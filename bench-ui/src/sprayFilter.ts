import library from '../../library/spray_pgn_library.json';

export type SprayCategory =
  | 'gps_motion'
  | 'rate_section'
  | 'flow_pressure'
  | 'boom_height'
  | 'spray_proprietary';

export interface SprayPgnEntry {
  pgn: number;
  name: string;
  category: SprayCategory;
  status: string;
  notes: string;
}

const WATCH_SAS = new Set(
  library.watch_sas.map((h) => parseInt(h, 16)),
);

const PGN_MAP = new Map<number, SprayPgnEntry>();
for (const e of library.entries as SprayPgnEntry[]) {
  PGN_MAP.set(e.pgn, e);
  // Also index by 0xPGN hex form used in monitor
  const hexKey = e.pgn <= 0xffff ? e.pgn : e.pgn;
  PGN_MAP.set(hexKey, e);
}

/** UI noise — VT/WSM/our own TC announce; never spray signal. */
export function isUiNoise(pgn: number, sa: number, da: number): boolean {
  if (pgn === 0xfe0d) return true;
  if (pgn === 0xe700) return true;
  if (pgn === 0xcb00 && da === 0xff && sa === 0x80) return true; // our TC announce
  return false;
}

export function frameInSprayLibrary(pgn: number, sa: number, pf: number): boolean {
  if (PGN_MAP.has(pgn)) return true;
  if (pf === 0xa0 || pf === 0xcb) return true;
  if (WATCH_SAS.has(sa)) return true;
  return false;
}

export function pgnMeta(pgn: number): SprayPgnEntry {
  const hit = PGN_MAP.get(pgn);
  if (hit) return hit;
  return {
    pgn,
    name: `PGN 0x${pgn.toString(16).toUpperCase().padStart(4, '0')}`,
    category: 'spray_proprietary',
    status: 'unknown',
    notes: 'Not in catalog yet — promote after field decode.',
  };
}

export const SPRAY_CATEGORIES: { id: SprayCategory; label: string }[] = [
  { id: 'gps_motion', label: 'GPS / motion' },
  { id: 'rate_section', label: 'Rate / section' },
  { id: 'flow_pressure', label: 'Flow / pressure' },
  { id: 'boom_height', label: 'Boom height' },
  { id: 'spray_proprietary', label: 'Proprietary' },
];

export const CATEGORY_COLORS: Record<SprayCategory, string> = {
  gps_motion: 'var(--cat-gps)',
  rate_section: 'var(--cat-rate)',
  flow_pressure: 'var(--cat-flow)',
  boom_height: 'var(--cat-boom)',
  spray_proprietary: 'var(--cat-prop)',
};
