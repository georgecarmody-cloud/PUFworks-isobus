import { SprayCategory } from './sprayFilter';

export interface ExportFrame {
  t: number;
  id: number;
  sa: number;
  da: number;
  pgn: number;
  dlc: number;
  data: string;
  pgnName: string;
  category: SprayCategory;
  saLabel: string;
}

const SA_SHORT: Record<number, string> = {
  0x94: 'GWC', 0x17: 'SRC', 0xe1: 'SRC', 0x68: 'MNC', 0x8a: 'BHC',
  0x1c: 'ATX', 0xcc: 'GRC', 0xf7: 'JD_SEC',
};

function shortSa(sa: number): string {
  return SA_SHORT[sa] ?? `SA${sa.toString(10).padStart(3, '0')}`;
}

/** Same columns as bus_engine recorder frames.csv (spray-enriched). */
export function framesToCsv(frames: ExportFrame[]): string {
  const header =
    'timestamp_ms,dir,can_id,sa_hex,sa_dec,sa_label,' +
    'pgn_hex,pgn_dec,pgn_name,category,da_hex,dlc,data_hex\n';
  const lines = frames.map((f) => {
    const saHex = `0x${f.sa.toString(16).toUpperCase().padStart(2, '0')}`;
    const pgnHex = `0x${f.pgn.toString(16).toUpperCase().padStart(4, '0')}`;
    const daHex = `0x${f.da.toString(16).toUpperCase().padStart(2, '0')}`;
    const canId = `0x${f.id.toString(16).toUpperCase().padStart(8, '0')}`;
    const esc = (s: string) => (s.includes(',') ? `"${s.replace(/"/g, '""')}"` : s);
    return [
      f.t,
      'RX',
      canId,
      saHex,
      f.sa,
      esc(f.saLabel || shortSa(f.sa)),
      pgnHex,
      f.pgn,
      esc(f.pgnName),
      f.category,
      daHex,
      f.dlc,
      f.data.toUpperCase(),
    ].join(',');
  });
  return header + lines.join('\n') + (lines.length ? '\n' : '');
}

export function downloadCsv(filename: string, content: string): void {
  const blob = new Blob([content], { type: 'text/csv;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}
