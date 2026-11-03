/** Normalises an Indian mobile number to E.164 (+91XXXXXXXXXX). Returns null if invalid. */
export function normalizeMobile(input: string): string | null {
  const d = input.replace(/[\s-]/g, '').replace(/^\+/, '');
  if (/^[6-9]\d{9}$/.test(d)) return `+91${d}`;
  if (/^91[6-9]\d{9}$/.test(d)) return `+${d}`;
  return null;
}

export function passwordProblem(pw: string): string | null {
  if (pw.length < 8) return 'Use at least 8 characters';
  if (!/[A-Za-z]/.test(pw) || !/\d/.test(pw)) return 'Include both letters and numbers';
  return null;
}

export const TERMS_VERSION = 'v1';
