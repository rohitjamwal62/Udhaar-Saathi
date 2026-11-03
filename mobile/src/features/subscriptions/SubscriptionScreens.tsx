import React, { useRef } from 'react';
import { Alert, Linking, View } from 'react-native';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useNavigation } from '@react-navigation/native';
import type { NativeStackNavigationProp } from '@react-navigation/native-stack';
import type { RootStackParamList } from '../../app/types';
import { Screen } from '../../shared/components/Screen';
import { AppText, Badge, Banner, Button, Card, EmptyState, ErrorState, KeyValue, Loading } from '../../shared/components/ui';
import { colors, spacing } from '../../core/theme';
import { formatPaise } from '../../core/money';
import { formatDate, formatDateTime } from '../../core/dates';
import { newId } from '../../core/ids';
import { config } from '../../core/config';
import { useAuth } from '../../core/auth/AuthContext';
import { subscriptionApi, type SubscriptionStatus } from '../../core/api/endpoints';
import { openCheckout } from './razorpay';

type Nav = NativeStackNavigationProp<RootStackParamList>;

const STATUS_COPY: Record<SubscriptionStatus, { label: string; tone: 'success' | 'warning' | 'danger' | 'info' | 'neutral' }> = {
  TRIALING: { label: 'Free trial', tone: 'success' },
  ACTIVE: { label: 'Active', tone: 'success' },
  PAYMENT_PENDING: { label: 'Payment being verified', tone: 'warning' },
  PAST_DUE: { label: 'Payment failed', tone: 'danger' },
  GRACE_PERIOD: { label: 'Grace period', tone: 'warning' },
  CANCELED: { label: 'Renewal canceled', tone: 'neutral' },
  EXPIRED: { label: 'Expired', tone: 'danger' },
  SUSPENDED: { label: 'Suspended', tone: 'danger' },
};

export function SubscriptionScreen() {
  const nav = useNavigation<Nav>();
  const qc = useQueryClient();
  const { user } = useAuth();
  const sub = useQuery({ queryKey: ['subscription'], queryFn: subscriptionApi.current, enabled: !config.demoMode });
  // One idempotency key per checkout attempt, reused on retry of the same attempt.
  const attemptKey = useRef(newId());

  const pay = useMutation({
    mutationFn: async () => {
      const order = await subscriptionApi.createOrder({ idempotency_key: attemptKey.current });
      const r = await openCheckout(order, { contact: user?.mobile, name: user?.name });
      // Access is granted only after the server verifies the signature / webhook.
      await subscriptionApi.verifyPayment({ order_id: r.orderId, payment_id: r.paymentId, signature: r.signature });
      attemptKey.current = newId();
    },
    onSettled: () => { void qc.invalidateQueries({ queryKey: ['subscription'] }); },
  });

  const cancel = useMutation({
    mutationFn: subscriptionApi.cancelRenewal,
    onSuccess: () => { void qc.invalidateQueries({ queryKey: ['subscription'] }); },
  });

  const confirmCancel = () =>
    Alert.alert('Cancel renewal?', 'You keep access until the end of the period you already paid for. Your records are never deleted.', [
      { text: 'Keep subscription', style: 'cancel' },
      { text: 'Cancel renewal', style: 'destructive', onPress: () => cancel.mutate() },
    ]);

  const s = sub.data;
  return (
    <Screen>
      <Card>
        <AppText variant="heading">UdhaarSaathi plan</AppText>
        <AppText variant="display" color={colors.primary}>₹49 <AppText color={colors.textMuted}>/ month</AppText></AppText>
        <AppText color={colors.textMuted}>Registration is free. Every new shop gets one 3-month free trial, then ₹49 per month. Cancel any time.</AppText>
        <AppText variant="caption" color={colors.textMuted}>{s?.taxes_note ?? 'Applicable taxes and gateway charges are shown before you pay.'}</AppText>
      </Card>

      {config.demoMode ? (
        <Banner tone="info">Demo mode: subscription needs the server.</Banner>
      ) : sub.isLoading ? <Loading /> : sub.error || !s ? (
        <ErrorState message="Could not load your subscription. Your khata still works offline." onRetry={() => void sub.refetch()} />
      ) : (
        <Card>
          <View style={{ flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' }}>
            <AppText variant="heading">Your status</AppText>
            <Badge label={STATUS_COPY[s.status].label} tone={STATUS_COPY[s.status].tone} />
          </View>
          {s.trial_ends_at && s.status === 'TRIALING' ? <KeyValue label="Trial ends" value={formatDate(s.trial_ends_at)} strong /> : null}
          {s.current_period_end ? <KeyValue label="Paid through" value={formatDate(s.current_period_end)} strong /> : null}
          {s.grace_ends_at && (s.status === 'GRACE_PERIOD' || s.status === 'PAST_DUE') ? <KeyValue label="Grace period ends" value={formatDate(s.grace_ends_at)} /> : null}
          {s.cancel_at_period_end ? <AppText color={colors.warning}>Renewal is canceled. You will not be charged again.</AppText> : null}
          {s.status === 'EXPIRED' || s.status === 'GRACE_PERIOD' || s.status === 'PAST_DUE' ? (
            <Banner tone="warning">If payment is not made, paid features become read-only. Your ledger history and exports always stay available.</Banner>
          ) : null}
          {s.status === 'PAYMENT_PENDING' ? <Banner tone="warning">We are waiting for the payment provider to confirm your payment. This can take a few minutes.</Banner> : null}
        </Card>
      )}

      {pay.error ? <Banner tone="danger">{(pay.error as Error).message}</Banner> : null}
      {pay.isSuccess ? <Banner tone="success">Payment submitted. Your plan updates once the server confirms it.</Banner> : null}

      {!config.demoMode ? (
        <View style={{ gap: spacing.sm }}>
          <Button title="Pay ₹49 for the next month" loading={pay.isPending} onPress={() => pay.mutate()} />
          <AppText variant="caption" color={colors.textMuted}>
            One-time payment via UPI, card or net banking (where enabled). Automatic renewal (UPI AutoPay / card mandate) is offered only after you give explicit consent, and is not available yet.
          </AppText>
          {s && !s.cancel_at_period_end && (s.status === 'ACTIVE' || s.status === 'TRIALING') ? (
            <Button title="Cancel future renewal" variant="ghost" loading={cancel.isPending} onPress={confirmCancel} />
          ) : null}
        </View>
      ) : null}
      <Button title="Payment history" variant="secondary" onPress={() => nav.navigate('PaymentHistory')} />
      <Button title="Terms and cancellation policy" variant="ghost" onPress={() => void Linking.openURL('https://udhaarsaathi.example/terms')} />
    </Screen>
  );
}

export function PaymentHistoryScreen() {
  const q = useQuery({ queryKey: ['payments'], queryFn: subscriptionApi.history, enabled: !config.demoMode });
  if (config.demoMode) return <Screen><EmptyState title="Not available in demo mode" /></Screen>;
  if (q.isLoading) return <Screen><Loading /></Screen>;
  if (q.error) return <Screen><ErrorState message={(q.error as Error).message} onRetry={() => void q.refetch()} /></Screen>;
  const rows = q.data?.results ?? [];
  return (
    <Screen>
      {rows.length === 0 ? <EmptyState title="No payments yet" body="Invoices and receipts appear here after your first payment." /> : rows.map((p) => (
        <Card key={p.id}>
          <View style={{ flexDirection: 'row', justifyContent: 'space-between', gap: spacing.sm }}>
            <AppText variant="bodyStrong">{formatPaise(p.amount_paise)}</AppText>
            <Badge label={p.status} tone={p.status === 'success' ? 'success' : p.status === 'failed' ? 'danger' : 'warning'} />
          </View>
          <AppText variant="caption" color={colors.textMuted}>{formatDateTime(p.created_at)}{p.method ? ` · ${p.method}` : ''}</AppText>
          {p.invoice_url ? <Button title="Open invoice" variant="ghost" onPress={() => void Linking.openURL(p.invoice_url as string)} /> : null}
        </Card>
      ))}
    </Screen>
  );
}
