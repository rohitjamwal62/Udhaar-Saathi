export type RangeKey = 'today' | 'yesterday' | 'week' | 'month' | 'prevMonth' | 'custom';

export interface DateRange {
  fromIso: string; // inclusive
  toIso: string; // exclusive
}

const startOfDay = (d: Date) => new Date(d.getFullYear(), d.getMonth(), d.getDate());
const addDays = (d: Date, n: number) => new Date(d.getFullYear(), d.getMonth(), d.getDate() + n);

export function rangeFor(key: Exclude<RangeKey, 'custom'>, now = new Date()): DateRange {
  const today = startOfDay(now);
  let from: Date;
  let to: Date;
  switch (key) {
    case 'today':
      from = today;
      to = addDays(today, 1);
      break;
    case 'yesterday':
      from = addDays(today, -1);
      to = today;
      break;
    case 'week': {
      const dow = (today.getDay() + 6) % 7; // Monday-based
      from = addDays(today, -dow);
      to = addDays(today, 1);
      break;
    }
    case 'month':
      from = new Date(today.getFullYear(), today.getMonth(), 1);
      to = addDays(today, 1);
      break;
    case 'prevMonth':
      from = new Date(today.getFullYear(), today.getMonth() - 1, 1);
      to = new Date(today.getFullYear(), today.getMonth(), 1);
      break;
  }
  return { fromIso: from.toISOString(), toIso: to.toISOString() };
}

/** Parse "YYYY-MM-DD" typed by the user into a local-midnight Date, or null. */
export function parseDay(s: string): Date | null {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(s.trim());
  if (!m) return null;
  const d = new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]));
  return d.getMonth() === Number(m[2]) - 1 ? d : null;
}

export function customRange(fromDay: string, toDay: string): DateRange | null {
  const f = parseDay(fromDay);
  const t = parseDay(toDay);
  if (!f || !t || t < f) return null;
  return { fromIso: f.toISOString(), toIso: addDays(t, 1).toISOString() };
}

export function formatDate(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleDateString('en-IN', { day: '2-digit', month: 'short', year: 'numeric' });
}

export function formatDateTime(iso: string): string {
  const d = new Date(iso);
  return `${formatDate(iso)}, ${d.toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit' })}`;
}

export function dayStamp(d = new Date()): string {
  const p = (n: number) => String(n).padStart(2, '0');
  return `${d.getFullYear()}${p(d.getMonth() + 1)}${p(d.getDate())}`;
}
