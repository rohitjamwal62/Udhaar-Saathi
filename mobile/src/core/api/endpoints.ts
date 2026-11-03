import { api } from './client';

// Typed wrappers for the Django /api/v1 contract. Authorization, entitlements and
// all financial rules are enforced by the server; the app only presents the result.

export interface AuthSession {
  access: string;
  refresh: string;
  user: { id: string; name: string; mobile: string; roles: string[] };
}

export const authApi = {
  signup: (b: { mobile: string; name: string; password: string; role: 'shopkeeper' | 'customer'; language: string; accepted_terms_version: string }) =>
    api<{ challenge_id: string }>('/auth/signup', { method: 'POST', body: b, auth: false }),
  requestOtp: (b: { mobile: string; purpose: 'signup' | 'login' | 'recovery' }) =>
    api<{ challenge_id: string }>('/auth/otp/request', { method: 'POST', body: b, auth: false }),
  verifyOtp: (b: { mobile: string; challenge_id: string; otp: string }) =>
    api<AuthSession>('/auth/otp/verify', { method: 'POST', body: b, auth: false }),
  login: (b: { mobile: string; password: string; device_id: string }) =>
    api<AuthSession>('/auth/login', { method: 'POST', body: b, auth: false }),
  logout: () => api<void>('/auth/logout', { method: 'POST' }),
  forgotPassword: (b: { mobile: string }) =>
    api<{ challenge_id: string }>('/auth/password/forgot', { method: 'POST', body: b, auth: false }),
  resetPassword: (b: { mobile: string; challenge_id: string; otp: string; new_password: string }) =>
    api<void>('/auth/password/reset', { method: 'POST', body: b, auth: false }),
};

export interface AppConfig {
  latest_version: string;
  minimum_supported_version: string;
  force_update: boolean;
  message?: string;
}
export const appApi = {
  config: () => api<AppConfig>('/app/config', { auth: false }),
};

export interface SyncItem { idempotency_key: string; entity: string; op: string; payload: unknown }
export interface SyncResult {
  idempotency_key: string;
  status: 'accepted' | 'duplicate' | 'conflict' | 'rejected';
  server_id?: string;
  error?: string;
}
export const syncApi = {
  batch: (b: { device_id: string; items: SyncItem[] }) =>
    api<{ results: SyncResult[]; cursor: string }>('/sync/batch', { method: 'POST', body: b }),
};

export type SubscriptionStatus =
  | 'TRIALING' | 'ACTIVE' | 'PAYMENT_PENDING' | 'PAST_DUE'
  | 'GRACE_PERIOD' | 'CANCELED' | 'EXPIRED' | 'SUSPENDED';

export interface SubscriptionInfo {
  status: SubscriptionStatus;
  plan_code: string;
  amount_paise: number;
  billing_interval: 'month';
  trial_ends_at: string | null;
  current_period_end: string | null;
  grace_ends_at: string | null;
  cancel_at_period_end: boolean;
  taxes_note: string;
}
export interface PaymentRecord {
  id: string;
  amount_paise: number;
  status: 'pending' | 'success' | 'failed' | 'refunded';
  method: string | null;
  created_at: string;
  invoice_url: string | null;
}
export interface CheckoutOrder {
  order_id: string; // Razorpay order id created by the server
  key_id: string; // public key id only; the secret never leaves the server
  amount_paise: number;
  currency: 'INR';
}
export const subscriptionApi = {
  current: () => api<SubscriptionInfo>('/subscriptions/current'),
  history: () => api<{ results: PaymentRecord[] }>('/subscriptions/payments'),
  createOrder: (b: { idempotency_key: string }) =>
    api<CheckoutOrder>('/subscriptions/orders', { method: 'POST', body: b }),
  // Activation happens only after the server verifies this signature / the webhook.
  verifyPayment: (b: { order_id: string; payment_id: string; signature: string }) =>
    api<{ status: SubscriptionStatus }>('/subscriptions/verify', { method: 'POST', body: b }),
  cancelRenewal: () => api<SubscriptionInfo>('/subscriptions/cancel', { method: 'POST' }),
};
