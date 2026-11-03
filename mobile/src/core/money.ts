// All money is integer paise. Never use floating point for amounts.
// Quantities are integer milli-units (1.5 kg = 1500) so line totals stay exact.

export type Paise = number;

const RUPEE_RE = /^\d{1,10}(\.\d{1,2})?$/;
const QTY_RE = /^\d{1,7}(\.\d{1,3})?$/;

/** Parse a user-typed rupee string ("1250", "1250.5") to paise. Returns null if invalid. */
export function parseRupees(input: string): Paise | null {
  const s = input.trim().replace(/,/g, '');
  if (!RUPEE_RE.test(s)) return null;
  const [whole, frac = ''] = s.split('.');
  return Number(whole) * 100 + Number(frac.padEnd(2, '0'));
}

/** Parse a quantity string to milli-units. Returns null if invalid or zero. */
export function parseQuantity(input: string): number | null {
  const s = input.trim();
  if (!QTY_RE.test(s)) return null;
  const [whole, frac = ''] = s.split('.');
  const milli = Number(whole) * 1000 + Number(frac.padEnd(3, '0'));
  return milli > 0 ? milli : null;
}

/** unit price (paise) * quantity (milli) -> line total paise, rounded half up. */
export function lineTotal(unitPricePaise: Paise, qtyMilli: number): Paise {
  return Math.floor((unitPricePaise * qtyMilli + 500) / 1000);
}

function groupIndian(whole: string): string {
  if (whole.length <= 3) return whole;
  const last3 = whole.slice(-3);
  const rest = whole.slice(0, -3).replace(/\B(?=(\d{2})+(?!\d))/g, ',');
  return `${rest},${last3}`;
}

/** Format paise as ₹1,23,456 or ₹1,23,456.50 (decimals only when needed). */
export function formatPaise(paise: Paise, opts: { showSign?: boolean } = {}): string {
  const neg = paise < 0;
  const abs = Math.abs(paise);
  const whole = Math.floor(abs / 100);
  const frac = abs % 100;
  const body = groupIndian(String(whole)) + (frac ? `.${String(frac).padStart(2, '0')}` : '');
  const sign = neg ? '-' : opts.showSign && paise > 0 ? '+' : '';
  return `${sign}₹${body}`;
}

export function formatQuantity(qtyMilli: number): string {
  const whole = Math.floor(qtyMilli / 1000);
  const frac = qtyMilli % 1000;
  return frac ? `${whole}.${String(frac).padStart(3, '0').replace(/0+$/, '')}` : String(whole);
}

/** Paise -> plain editable rupee string ("123.45", "100") using integer math only. */
export function paiseToInput(paise: Paise): string {
  const whole = Math.floor(Math.abs(paise) / 100);
  const frac = Math.abs(paise) % 100;
  return frac ? `${whole}.${String(frac).padStart(2, '0')}` : String(whole);
}
