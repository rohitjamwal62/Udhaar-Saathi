/** Compares dotted version strings numerically. Returns <0, 0 or >0. */
export function compareVersions(a: string, b: string): number {
  const pa = a.split('.').map((n) => parseInt(n, 10) || 0);
  const pb = b.split('.').map((n) => parseInt(n, 10) || 0);
  for (let i = 0; i < Math.max(pa.length, pb.length); i++) {
    const d = (pa[i] ?? 0) - (pb[i] ?? 0);
    if (d !== 0) return d;
  }
  return 0;
}

export type UpdateDecision = 'none' | 'optional' | 'required';

export function decideUpdate(
  current: string,
  cfg: { latest_version: string; minimum_supported_version: string; force_update: boolean },
): UpdateDecision {
  if (compareVersions(current, cfg.minimum_supported_version) < 0) return 'required';
  if (compareVersions(current, cfg.latest_version) < 0) return cfg.force_update ? 'required' : 'optional';
  return 'none';
}
