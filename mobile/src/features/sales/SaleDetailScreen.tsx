import React, { useState } from 'react';
import { Share, View } from 'react-native';
import { useRoute, type RouteProp } from '@react-navigation/native';
import type { RootStackParamList } from '../../app/types';
import { Screen } from '../../shared/components/Screen';
import { TextField } from '../../shared/components/TextField';
import { SyncBadge } from '../../shared/components/badges';
import { AppText, Banner, Button, Card, Chip, ChipRow, ErrorState, KeyValue, Loading } from '../../shared/components/ui';
import { colors, spacing } from '../../core/theme';
import { formatPaise, formatQuantity, parseRupees } from '../../core/money';
import { formatDateTime } from '../../core/dates';
import { addReturn } from '../../core/db/repo';
import type { PayMethod } from '../../core/db/types';
import { useAction, useAfterWrite } from '../../shared/hooks';
import { useSaleDetail, useShop } from '../../shared/queries';

const REFUND: (PayMethod | 'khata')[] = ['cash', 'upi', 'card', 'bank', 'other', 'khata'];

export function SaleDetailScreen() {
  const { saleId } = useRoute<RouteProp<RootStackParamList, 'SaleDetail'>>().params;
  const q = useSaleDetail(saleId);
  const shop = useShop();
  const afterWrite = useAfterWrite();
  const [showReturn, setShowReturn] = useState(false);
  const [amount, setAmount] = useState('');
  const [reason, setReason] = useState('');
  const [method, setMethod] = useState<PayMethod | 'khata'>('cash');

  const doReturn = useAction(async () => {
    const paise = parseRupees(amount);
    if (paise === null || paise <= 0) throw new Error('Enter a valid return amount');
    await addReturn(saleId, paise, reason, method);
    setShowReturn(false); setAmount(''); setReason('');
    await afterWrite();
  });

  if (q.isLoading) return <Screen><Loading /></Screen>;
  if (!q.data) return <Screen><ErrorState message="Sale not found." /></Screen>;
  const { sale, items, payments, returns, customerName, netPaise } = q.data;

  const share = () => {
    const lines = [
      `${shop.data?.name ?? 'Shop'} - Receipt ${sale.sale_number}`,
      formatDateTime(sale.sale_at),
      ...items.map((i) => `${i.item_name} ${formatQuantity(i.quantity_milli)}${i.unit ? ` ${i.unit}` : ''} x ${formatPaise(i.unit_price_paise)} = ${formatPaise(i.line_total_paise)}`),
      `Gross ${formatPaise(sale.gross_paise)}  Discount ${formatPaise(sale.discount_paise)}`,
      `Total ${formatPaise(sale.gross_paise - sale.discount_paise)}`,
      ...payments.map((p) => `${p.method === 'credit' ? 'On credit' : p.method.toUpperCase()}: ${formatPaise(p.amount_paise)}`),
      'This is a sale receipt, not a GST tax invoice.',
    ];
    return Share.share({ message: lines.join('\n') });
  };

  return (
    <Screen>
      <Card>
        <AppText variant="title">{sale.sale_number}</AppText>
        <AppText color={colors.textMuted}>{formatDateTime(sale.sale_at)}{customerName ? ` · ${customerName}` : ''}</AppText>
        <SyncBadge status={sale.sync_status} />
        <KeyValue label="Gross" value={formatPaise(sale.gross_paise)} />
        <KeyValue label="Discount" value={`− ${formatPaise(sale.discount_paise)}`} />
        <KeyValue label="Returns" value={`− ${formatPaise(sale.gross_paise - sale.discount_paise - netPaise)}`} />
        <KeyValue label="Net sale" value={formatPaise(netPaise)} strong />
      </Card>

      {items.length ? (
        <Card>
          <AppText variant="heading">Items</AppText>
          {items.map((i) => (
            <KeyValue key={i.id} label={`${i.item_name} · ${formatQuantity(i.quantity_milli)}${i.unit ? ` ${i.unit}` : ''} × ${formatPaise(i.unit_price_paise)}`}
              value={formatPaise(i.line_total_paise)} />
          ))}
        </Card>
      ) : <AppText color={colors.textMuted}>Quick sale (no item details)</AppText>}

      <Card>
        <AppText variant="heading">Payments</AppText>
        {payments.map((p) => (
          <KeyValue key={p.id} label={p.method === 'credit' ? 'On credit (khata)' : p.method.toUpperCase()} value={formatPaise(p.amount_paise)} />
        ))}
      </Card>

      {returns.length ? (
        <Card>
          <AppText variant="heading">Returns / refunds</AppText>
          {returns.map((r) => (
            <KeyValue key={r.id} label={`${formatDateTime(r.returned_at)} · ${r.refund_method === 'khata' ? 'to khata' : r.refund_method.toUpperCase()}${r.reason ? ` · ${r.reason}` : ''}`}
              value={formatPaise(r.return_paise)} />
          ))}
        </Card>
      ) : null}

      {showReturn ? (
        <Card>
          <AppText variant="heading">Record a return</AppText>
          <TextField label="Return amount" prefix="₹" keyboardType="decimal-pad" value={amount} onChangeText={setAmount}
            helper={`Up to ${formatPaise(netPaise)}`} />
          <TextField label="Reason" value={reason} onChangeText={setReason} />
          <AppText variant="label">Refunded via</AppText>
          <ChipRow>
            {REFUND.filter((m) => m !== 'khata' || sale.customer_id).map((m) => (
              <Chip key={m} label={m === 'khata' ? 'Reduce khata' : m.toUpperCase()} selected={method === m} onPress={() => setMethod(m)} />
            ))}
          </ChipRow>
          {doReturn.error ? <Banner tone="danger">{doReturn.error}</Banner> : null}
          <View style={{ gap: spacing.sm }}>
            <Button title="Save return" loading={doReturn.busy} onPress={() => doReturn.run()} />
            <Button title="Cancel" variant="ghost" onPress={() => setShowReturn(false)} />
          </View>
        </Card>
      ) : (
        <View style={{ gap: spacing.sm }}>
          <Button title="Return / refund" variant="secondary" disabled={netPaise <= 0} onPress={() => setShowReturn(true)} />
          <Button title="Share receipt" variant="ghost" onPress={() => void share()} />
        </View>
      )}
    </Screen>
  );
}
