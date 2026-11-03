import React, { useMemo, useState } from 'react';
import { View } from 'react-native';
import { useNavigation } from '@react-navigation/native';
import type { NativeStackNavigationProp } from '@react-navigation/native-stack';
import type { RootStackParamList } from '../../app/types';
import { Screen } from '../../shared/components/Screen';
import { TextField } from '../../shared/components/TextField';
import { SyncBadge } from '../../shared/components/badges';
import { AppText, Button, Card, Chip, ChipRow, EmptyState, KeyValue, Loading, Row, SectionHeader } from '../../shared/components/ui';
import { colors, spacing } from '../../core/theme';
import { formatPaise } from '../../core/money';
import { customRange, formatDateTime, rangeFor, type DateRange, type RangeKey } from '../../core/dates';
import { useSales, useSalesSummary } from '../../shared/queries';

type Nav = NativeStackNavigationProp<RootStackParamList>;

export const RANGE_LABELS: Record<RangeKey, string> = {
  today: 'Today', yesterday: 'Yesterday', week: 'This week', month: 'This month', prevMonth: 'Last month', custom: 'Custom',
};

/** Range chips shared by Sales and Reports. */
export function useRangePicker() {
  const [key, setKey] = useState<RangeKey>('today');
  const [from, setFrom] = useState('');
  const [to, setTo] = useState('');
  const range: DateRange | null = useMemo(
    () => (key === 'custom' ? customRange(from, to) : rangeFor(key)),
    [key, from, to],
  );
  const ui = (
    <View style={{ gap: spacing.sm }}>
      <ChipRow>
        {(Object.keys(RANGE_LABELS) as RangeKey[]).map((k) => (
          <Chip key={k} label={RANGE_LABELS[k]} selected={k === key} onPress={() => setKey(k)} />
        ))}
      </ChipRow>
      {key === 'custom' ? (
        <View style={{ flexDirection: 'row', gap: spacing.sm }}>
          <View style={{ flex: 1 }}><TextField label="From" value={from} onChangeText={setFrom} placeholder="YYYY-MM-DD" autoCapitalize="none" /></View>
          <View style={{ flex: 1 }}><TextField label="To" value={to} onChangeText={setTo} placeholder="YYYY-MM-DD" autoCapitalize="none"
            error={from && to && !range ? 'Check the dates' : null} /></View>
        </View>
      ) : null}
    </View>
  );
  return { key, range: range ?? rangeFor('today'), valid: !!range, ui };
}

export function SalesScreen() {
  const nav = useNavigation<Nav>();
  const picker = useRangePicker();
  const summary = useSalesSummary(picker.range);
  const sales = useSales(picker.range);
  const s = summary.data;

  return (
    <Screen>
      <Button title="+ New sale" onPress={() => nav.navigate('NewSale')} />
      {picker.ui}
      {summary.isLoading ? <Loading /> : s ? (
        <Card>
          <AppText variant="caption" color={colors.textMuted}>Net sales</AppText>
          <AppText variant="display" color={colors.primary}>{formatPaise(s.netPaise)}</AppText>
          <KeyValue label="Gross sales" value={formatPaise(s.grossPaise)} />
          <KeyValue label="Discounts" value={`− ${formatPaise(s.discountPaise)}`} />
          <KeyValue label="Returns / refunds" value={`− ${formatPaise(s.returnsPaise)}`} />
          <View style={{ height: spacing.sm }} />
          <KeyValue label="Collected at sale (cash/UPI/card)" value={formatPaise(s.collectedPaise)} strong />
          <KeyValue label="Credit sales (added to khata)" value={formatPaise(s.creditSalesPaise)} strong />
          <KeyValue label="Old dues collected (not sales)" value={formatPaise(s.oldDuesCollectedPaise)} />
          <AppText variant="caption" color={colors.textMuted}>
            Collections are cash flow, not sales. Payments against earlier udhaar are never counted as new sales.
          </AppText>
        </Card>
      ) : null}

      <SectionHeader title={`Sales (${sales.data?.length ?? 0})`} />
      {sales.data?.length === 0 ? (
        <EmptyState title="No sales in this period" body="Sales appear here only when you enter them. UdhaarSaathi does not know about sales you have not recorded." />
      ) : (
        <View style={{ gap: spacing.sm }}>
          {sales.data?.map((x) => (
            <Card key={x.id}>
              <Row
                onPress={() => nav.navigate('SaleDetail', { saleId: x.id })}
                left={
                  <View style={{ gap: 2 }}>
                    <AppText variant="bodyStrong">{x.sale_number}</AppText>
                    <AppText variant="caption" color={colors.textMuted}>
                      {formatDateTime(x.sale_at)}{x.customer_name ? ` · ${x.customer_name}` : ''}
                    </AppText>
                    <SyncBadge status={x.sync_status} />
                  </View>
                }
                right={
                  <View style={{ alignItems: 'flex-end' }}>
                    <AppText variant="bodyStrong">{formatPaise(x.net_paise)}</AppText>
                    {x.returned_paise > 0 ? <AppText variant="caption" color={colors.warning}>returned {formatPaise(x.returned_paise)}</AppText> : null}
                  </View>
                }
              />
            </Card>
          ))}
        </View>
      )}
    </Screen>
  );
}
