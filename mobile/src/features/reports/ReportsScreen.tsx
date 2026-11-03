import React from 'react';
import { Share, View } from 'react-native';
import { useQuery } from '@tanstack/react-query';
import { Screen } from '../../shared/components/Screen';
import { AppText, Button, Card, EmptyState, KeyValue, Loading, SectionHeader } from '../../shared/components/ui';
import { colors, radius, spacing } from '../../core/theme';
import { formatPaise, formatQuantity } from '../../core/money';
import { formatDateTime } from '../../core/dates';
import { getDailyNet, getTopItems, listCustomers, listSales } from '../../core/db/repo';
import { useSalesSummary, useShop } from '../../shared/queries';
import { useRangePicker } from '../sales/SalesScreen';

const csvCell = (v: string | number) => `"${String(v).replace(/"/g, '""')}"`;

export function ReportsScreen() {
  const picker = useRangePicker();
  const shop = useShop();
  const summary = useSalesSummary(picker.range);
  const trend = useQuery({ queryKey: ['trend', picker.range.fromIso, picker.range.toIso], queryFn: () => getDailyNet(picker.range) });
  const top = useQuery({ queryKey: ['top', picker.range.fromIso, picker.range.toIso], queryFn: () => getTopItems(picker.range) });
  const owing = useQuery({
    queryKey: ['owing'],
    queryFn: async () => (await listCustomers('')).filter((c) => c.balance_paise > 0),
  });

  const exportCsv = async () => {
    const sales = await listSales(picker.range);
    const head = [
      `# ${shop.data?.name ?? 'Shop'} - sales export`,
      `# Generated at ${formatDateTime(new Date().toISOString())}`,
      'sale_number,date,customer,gross_rupees,discount_rupees,returned_rupees,net_rupees,sync_status',
    ];
    const r = (p: number) => (p / 100).toFixed(2); // display only; stored values stay integer paise
    const lines = sales.map((s) => [
      s.sale_number, s.sale_at, s.customer_name ?? '', r(s.gross_paise), r(s.discount_paise), r(s.returned_paise), r(s.net_paise), s.sync_status,
    ].map(csvCell).join(','));
    await Share.share({ message: [...head, ...lines].join('\n'), title: 'Sales export' });
  };

  const maxNet = Math.max(1, ...(trend.data ?? []).map((d) => Math.abs(d.net)));
  const s = summary.data;

  return (
    <Screen>
      {picker.ui}
      {summary.isLoading ? <Loading /> : s ? (
        <Card>
          <AppText variant="heading">Sales by payment mode</AppText>
          {Object.keys(s.byMethod).length === 0 ? <AppText color={colors.textMuted}>No sales in this period.</AppText> :
            Object.entries(s.byMethod).map(([m, v]) => (
              <KeyValue key={m} label={m === 'credit' ? 'On credit (khata)' : m.toUpperCase()} value={formatPaise(v)} />
            ))}
        </Card>
      ) : null}

      <SectionHeader title="Daily net sales" />
      <Card>
        {(trend.data?.length ?? 0) === 0 ? <AppText color={colors.textMuted}>No data for this period.</AppText> :
          trend.data?.map((d) => (
            <View key={d.day} style={{ gap: 2 }}>
              <View style={{ flexDirection: 'row', justifyContent: 'space-between' }}>
                <AppText variant="caption">{d.day}</AppText>
                <AppText variant="caption">{formatPaise(d.net)}</AppText>
              </View>
              <View style={{ height: 8, backgroundColor: colors.primarySoft, borderRadius: radius.sm }}>
                <View style={{ height: 8, width: `${Math.max(2, (Math.abs(d.net) / maxNet) * 100)}%`, backgroundColor: d.net < 0 ? colors.danger : colors.primary, borderRadius: radius.sm }} />
              </View>
            </View>
          ))}
      </Card>

      <SectionHeader title="Top items" />
      <Card>
        {(top.data?.length ?? 0) === 0 ? <AppText color={colors.textMuted}>Only itemized sales appear here.</AppText> :
          top.data?.map((t) => (
            <KeyValue key={t.item_name} label={`${t.item_name} (${formatQuantity(t.qty_milli)})`} value={formatPaise(t.value_paise)} />
          ))}
      </Card>

      <SectionHeader title="Customers who owe you" />
      {(owing.data?.length ?? 0) === 0 ? <EmptyState title="No outstanding balances" /> : (
        <Card>
          {owing.data?.map((c) => <KeyValue key={c.id} label={c.name} value={formatPaise(c.balance_paise)} />)}
          <AppText variant="caption" color={colors.textMuted}>
            Amounts are as recorded by you. They are not customer confirmed unless marked so on the customer's page.
          </AppText>
        </Card>
      )}

      <View style={{ gap: spacing.sm }}>
        <Button title="Export sales (CSV)" variant="secondary" onPress={() => void exportCsv()} />
      </View>
    </Screen>
  );
}
