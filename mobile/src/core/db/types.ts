export type SyncStatus = 'pending' | 'synced' | 'failed' | 'conflict';
export type PayMethod = 'cash' | 'upi' | 'card' | 'bank' | 'other';
export type SalePayMethod = PayMethod | 'credit';
export type ConfirmationStatus =
  | 'shopkeeper_recorded'
  | 'awaiting_confirmation'
  | 'customer_confirmed'
  | 'disputed'
  | 'expired';
export type LedgerType = 'opening' | 'credit' | 'payment' | 'adjustment' | 'reversal';

export interface Shop {
  id: string;
  name: string;
  category: string | null;
  address: string | null;
  owner_name: string | null;
  owner_mobile: string | null;
  timezone: string;
  language: string;
  created_at: string;
  sync_status: SyncStatus;
}

export interface Customer {
  id: string;
  name: string;
  mobile: string | null;
  notes: string | null;
  archived: number;
  created_at: string;
  sync_status: SyncStatus;
}

export interface CustomerWithBalance extends Customer {
  balance_paise: number;
  last_activity_at: string | null;
}

export interface LedgerItem {
  id: string;
  event_id: string;
  item_name: string;
  quantity_milli: number;
  unit: string | null;
  unit_price_paise: number;
  line_total_paise: number;
}

export interface LedgerEvent {
  id: string;
  customer_id: string;
  type: LedgerType;
  amount_paise: number;
  delta_paise: number;
  occurred_at: string;
  created_at: string;
  note: string | null;
  payment_method: PayMethod | null;
  payment_reference: string | null;
  sale_id: string | null;
  reversal_of_id: string | null;
  reason: string | null;
  confirmation_status: ConfirmationStatus;
  evidence_uri: string | null;
  idempotency_key: string;
  sync_status: SyncStatus;
}

export interface LedgerRow extends LedgerEvent {
  running_balance_paise: number;
  items: LedgerItem[];
  reversed: boolean;
}

export interface Sale {
  id: string;
  sale_number: string;
  customer_id: string | null;
  sale_type: 'quick' | 'itemized';
  sale_at: string;
  created_at: string;
  gross_paise: number;
  discount_paise: number;
  note: string | null;
  idempotency_key: string;
  sync_status: SyncStatus;
}

export interface SaleItem {
  id: string;
  sale_id: string;
  item_name: string;
  quantity_milli: number;
  unit: string | null;
  unit_price_paise: number;
  discount_paise: number;
  line_total_paise: number;
}

export interface SalePayment {
  id: string;
  sale_id: string;
  method: SalePayMethod;
  amount_paise: number;
  reference: string | null;
  paid_at: string;
}

export interface SaleReturn {
  id: string;
  sale_id: string;
  return_paise: number;
  reason: string | null;
  refund_method: PayMethod | 'khata';
  returned_at: string;
  idempotency_key: string;
  sync_status: SyncStatus;
}

export interface SaleListRow extends Sale {
  customer_name: string | null;
  returned_paise: number;
  net_paise: number;
}

export interface OutboxRow {
  id: string;
  entity: string;
  entity_id: string;
  op: string;
  payload: string;
  idempotency_key: string;
  status: 'pending' | 'failed' | 'conflict';
  attempts: number;
  next_attempt_at: number;
  last_error: string | null;
  seq: number;
  created_at: string;
}
