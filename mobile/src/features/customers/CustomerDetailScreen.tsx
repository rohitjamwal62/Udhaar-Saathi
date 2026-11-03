import React, { useState } from 'react';
import { Alert, FlatList, Share, View } from 'react-native';
import { useNavigation, useRoute, type RouteProp } from '@react-navigation/native';
import type { NativeStackNavigationProp } from '@react-navigation/native-stack';
import type { RootStackParamList } from '../../app/types';
import { Screen } from '../../shared/components/Screen';
import { AppText, Badge, Button, Card, EmptyState, ErrorState, Loading } from '../../shared/components/ui';
import { ConfirmationBadge, SyncBadge } from '../../shared/components/badges';
import { ReasonModal } from '../../shared/components/ReasonModal';
import { colors, spacing } from '../../core/theme';
import { formatPaise, formatQuantity } from '../../core/money';
import { formatDate, formatDateTime } from '../../core/dates';
import { archiveCustomer, reverseEvent } from '../../core/db/repo';
import type { LedgerRow } from '../../core/db/types';
import { useCustomer, useLedger, useShop } from '../../shared/queries';
import { useAfterWrite } from '../../shared/hooks';

type Nav = NativeStackNavigationProp<RootStackParamList>;

const TYPE_LABEL: Record<LedgerRow['type'], string> = {
  opening: 'Opening balance',
  credit: 'Credit given',
  payment: 'Payment received',
  adjustment: 'Adjustment',
  reversal: 'Reversal',
};

export function CustomerDetailScreen() {
  const nav = useNavigation<Nav>();
  const { customerId } = useRoute<RouteProp<RootStackParamList, 'CustomerDetail'>>().params;
  const customer = useCustomer(customerId);
  const ledger = useLedger(customerId);
  const shop = useShop();
  const afterWrite = useAfterWrite();
  const [reversing, setReversing] = useState<LedgerRow | null>(null);

  if (customer.isLoading || ledger.isLoading) return <Screen><Loading /></Screen>;
  if (customer.error || ledger.error || !customer.data) {
    return <Screen><ErrorState message="Could not load this customer." onRetry={() => { void customer.refetch(); void ledger.refetch(); }} /></Screen>;
  }
  const c = customer.data;
  const rows = [...(ledger.data ?? [])].reverse(); // newest first

  const shareStatement = async () => {
    const lines = [
      `${shop.data?.name ?? 'Shop'} - statement for ${c.name}`,
      `Generated: ${formatDateTime(new Date().toISOString())}`,
      ...(ledger.data ?? []).map((r) =>
        `${formatDate(r.occurred_at)}  ${TYPE_LABEL[r.type]}${r.reversed ? ' (reversed)' : ''}  ${formatPaise(r.delta_paise, { showSign: true })}  balance ${formatPaise(r.running_balance_paise)}`),
      `Outstanding: ${formatPaise(c.balance_paise)}`,
      'Entries are as recorded by the shopkeeper unless marked customer confirmed.',
    ];
    await Share.share({ message: lines.join('\n') });
  };

  const confirmArchive = () =>
    Alert.alert('Archive customer?', 'The customer is hidden from your list. All their entries are kept.', [
      { text: 'Cancel', style: 'cancel' },
      { text: 'Archive', style: 'destructive', onPress: async () => { await archiveCustomer(c.id); await afterWrite(); nav.goBack(); } },
    ]);

  return (
    <Screen scroll={false}>
      <FlatList
        style={{ width: '100%' }}
        data={rows}
        keyExtractor={(r) => r.id}
        contentContainerStyle={{ paddingBottom: spacing.xxl, gap: spacing.sm }}
        ListHeaderComponent={
          <View style={{ gap: spacing.md, marginBottom: spacing.md }}>
            <Card>
              <AppText variant="title">{c.name}</AppText>
              <AppText color={colors.textMuted}>{c.mobile ?? 'No phone number'}</AppText>
              <AppText variant="caption" color={colors.textMuted}>
                {c.balance_paise < 0 ? 'Advance held for customer' : 'Outstanding to collect'}
              </AppText>
              <AppText variant="display" color={c.balance_paise > 0 ? colors.danger : colors.success}>
                {formatPaise(Math.abs(c.balance_paise))}
              </AppText>
            </Card>
            <View style={{ gap: spacing.sm }}>
              <Button title="Add credit (goods on udhaar)" onPress={() => nav.navigate('AddCredit', { customerId })} />
              <Button title="Receive payment" variant="secondary" disabled={c.balance_paise <= 0}
                onPress={() => nav.navigate('ReceivePayment', { customerId })} />
              <Button title="Share statement" variant="ghost" onPress={() => void shareStatement()} />
            </View>
            <AppText variant="heading">History</AppText>
          </View>
        }
        ListEmptyComponent={<EmptyState title="No entries yet" body="Add a credit or opening balance to begin." />}
        ListFooterComponent={<Button title="Archive customer" variant="ghost" onPress={confirmArchive} />}
        renderItem={({ item: r }) => (
          <Card>
            <View style={{ flexDirection: 'row', justifyContent: 'space-between', gap: spacing.md }}>
              <View style={{ flex: 1, gap: 2 }}>
                <AppText variant="bodyStrong">{TYPE_LABEL[r.type]}</AppText>
                <AppText variant="caption" color={colors.textMuted}>{formatDateTime(r.occurred_at)}</AppText>
              </View>
              <AppText variant="bodyStrong"
                color={r.delta_paise > 0 ? colors.danger : colors.success}
                style={r.reversed ? { textDecorationLine: 'line-through' } : undefined}>
                {formatPaise(r.delta_paise, { showSign: true })}
              </AppText>
            </View>
            {r.items.length ? (
              <View>
                {r.items.map((i) => (
                  <AppText key={i.id} variant="caption" color={colors.textMuted}>
                    {i.item_name} · {formatQuantity(i.quantity_milli)}{i.unit ? ` ${i.unit}` : ''} × {formatPaise(i.unit_price_paise)} = {formatPaise(i.line_total_paise)}
                  </AppText>
                ))}
              </View>
            ) : r.type === 'credit' ? <AppText variant="caption" color={colors.textMuted}>Non-itemized entry</AppText> : null}
            {r.note ? <AppText variant="caption">{r.note}</AppText> : null}
            {r.reason ? <AppText variant="caption">Reason: {r.reason}</AppText> : null}
            {r.payment_method ? <AppText variant="caption" color={colors.textMuted}>Via {r.payment_method.toUpperCase()}{r.payment_reference ? ` · ${r.payment_reference}` : ''}</AppText> : null}
            {r.evidence_uri ? <Badge label="Bill attached" tone="info" /> : null}
            <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: spacing.xs }}>
              {r.type === 'credit' ? <ConfirmationBadge status={r.confirmation_status} /> : null}
              <SyncBadge status={r.sync_status} />
              {r.reversed ? <Badge label="Reversed" tone="neutral" /> : null}
            </View>
            <View style={{ flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap' }}>
              <AppText variant="caption" color={colors.textMuted}>Balance after: {formatPaise(r.running_balance_paise)}</AppText>
              {r.type !== 'reversal' && !r.reversed ? (
                <Button title="Reverse" variant="ghost" onPress={() => setReversing(r)} />
              ) : null}
            </View>
          </Card>
        )}
      />
      <ReasonModal
        visible={!!reversing}
        title="Reverse this entry?"
        description="The original entry stays visible. A new reversal entry with your reason is added and the balance is corrected."
        confirmLabel="Post reversal"
        onCancel={() => setReversing(null)}
        onConfirm={async (reason) => {
          if (reversing) await reverseEvent(reversing.id, reason);
          setReversing(null);
          await afterWrite();
        }}
      />
    </Screen>
  );
}
