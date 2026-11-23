/** Normalises an Indian mobile number to E.164 (+91XXXXXXXXXX). Returns null if invalid. */
export function normalizeMobile(input: string): string | null {
  const d = input.replace(/[\s-]/g, '').replace(/^\+/, '');
  if (/^[6-9]\d{9}$/.test(d)) return `+91${d}`;
  if (/^91[6-9]\d{9}$/.test(d)) return `+${d}`;
  return null;
}

/** Trims and lower-cases an email address. */
export function normalizeEmail(input: string): string {
  return input.trim().toLowerCase();
}

/** null when the address looks valid; otherwise the message to show. The server does the real check. */
export function emailProblem(input: string): string | null {
  const e = normalizeEmail(input);
  if (!e) return 'Enter your email address: we send your verification code there';
  if (!/^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/.test(e)) return 'Enter a valid email address';
  return null;
}

/** What the login box accepts: a mobile number or an email address. Returns the value to send, or null when it is neither. */
export function loginIdentifier(input: string): string | null {
  const t = input.trim();
  if (t.includes('@')) return emailProblem(t) ? null : normalizeEmail(t);
  return normalizeMobile(t);
}

export function passwordProblem(pw: string): string | null {
  if (pw.length < 8) return 'Use at least 8 characters';
  if (!/[A-Za-z]/.test(pw) || !/\d/.test(pw)) return 'Include both letters and numbers';
  return null;
}

export const TERMS_VERSION = 'v1';
