import React from 'react';
import { Badge } from './ui';
import type { ConfirmationStatus, SyncStatus } from '../../core/db/types';

const CONFIRMATION: Record<ConfirmationStatus, { label: string; tone: 'neutral' | 'warning' | 'success' | 'danger' }> = {
  shopkeeper_recorded: { label: 'Shopkeeper recorded', tone: 'neutral' },
  awaiting_confirmation: { label: 'Awaiting confirmation', tone: 'warning' },
  customer_confirmed: { label: 'Customer confirmed', tone: 'success' },
  disputed: { label: 'Disputed', tone: 'danger' },
  expired: { label: 'Confirmation expired', tone: 'neutral' },
};

export function ConfirmationBadge({ status }: { status: ConfirmationStatus }) {
  const c = CONFIRMATION[status];
  return <Badge label={c.label} tone={c.tone} />;
}

export function SyncBadge({ status }: { status: SyncStatus }) {
  if (status === 'synced') return <Badge label="Synced" tone="success" />;
  if (status === 'pending') return <Badge label="Pending sync" tone="warning" />;
  if (status === 'conflict') return <Badge label="Conflict: needs review" tone="danger" />;
  return <Badge label="Sync failed" tone="danger" />;
}
