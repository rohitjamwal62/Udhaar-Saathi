import React from 'react';
import { Pressable, View } from 'react-native';
import { useNavigation } from '@react-navigation/native';
import type { NativeStackNavigationProp } from '@react-navigation/native-stack';
import type { RootStackParamList } from '../../app/types';
import { Screen } from '../../shared/components/Screen';
import { AppText, Banner, Button, Card, KeyValue, Loading } from '../../shared/components/ui';
import { colors, spacing } from '../../core/theme';
import { formatPaise } from '../../core/money';
import { rangeFor } from '../../core/dates';
import { useKhataSummary, useSalesSummary, useShop } from '../../shared/queries';
import { useIsRegular } from '../../shared/hooks';
import { useSyncState } from '../../core/sync/SyncProvider';

type Nav = NativeStackNavigationProp<RootStackParamList>;

export function HomeScreen() {
  const nav = useNavigation<Nav>();
  const regular = useIsRegular();
  const shop = useShop();
  const khata = useKhataSummary();
  const today = useSalesSummary(rangeFor('today'));
  const month = useSalesSummary(rangeFor('month'));
  const sync = useSyncState();

  if (khata.isLoading || today.isLoading || month.isLoading) return <Screen><Loading /></Screen>;
  const k = khata.data;
  const unconfirmed = k?.creditByStatus.shopkeeper_recorded ?? 0;

  return (
    <Screen>
      <View>
        <AppText variant="title">{shop.data?.name ?? 'My shop'}</AppText>
        <AppText color={colors.textMuted}>Today's overview</AppText>
      </View>

      {sync.failed + sync.conflict > 0 ? (
        <Pressable onPress={() => nav.navigate('SyncStatus')}>
          <Banner tone="danger">{sync.failed + sync.conflict} entries need review. Tap to open sync status.</Banner>
        </Pressable>
      ) : sync.pending > 0 ? (
        <Pressable onPress={() => nav.navigate('SyncStatus')}>
          <Banner tone="warning">{sync.pending} entries saved on this phone, waiting to sync.</Banner>
        </Pressable>
      ) : null}

      <View style={{ flexDirection: regular ? 'row' : 'column', gap: spacing.md }}>
        <Card style={{ flex: regular ? 1 : undefined }}>
          <AppText variant="label" color={colors.primary}>UDHAAR / KHATA</AppText>
          <AppText variant="caption" color={colors.textMuted}>Total outstanding receivable</AppText>
          <AppText variant="display" color={colors.danger} accessibilityLabel={`Total receivable ${formatPaise(k?.totalReceivablePaise ?? 0)}`}>
            {formatPaise(k?.totalReceivablePaise ?? 0)}
          </AppText>
          <KeyValue label="Customers with balance" value={String(k?.customersWithBalance ?? 0)} />
          <KeyValue label="Credit: shopkeeper recorded" value={formatPaise(unconfirmed)} />
          <KeyValue label="Credit: awaiting confirmation" value={formatPaise(k?.creditByStatus.awaiting_confirmation ?? 0)} />
          <KeyValue label="Credit: customer confirmed" value={formatPaise(k?.creditByStatus.customer_confirmed ?? 0)} />
          <KeyValue label="Credit: disputed" value={formatPaise(k?.creditByStatus.disputed ?? 0)} />
          <Button title="Open khata" variant="secondary" onPress={() => nav.navigate('Main', { screen: 'Khata' })} />
        </Card>

        <Card style={{ flex: regular ? 1 : undefined }}>
          <AppText variant="label" color={colors.primary}>SALES TRACKING</AppText>
          <AppText variant="caption" color={colors.textMuted}>Today's net sales</AppText>
          <AppText variant="display" color={colors.primary}>{formatPaise(today.data?.netPaise ?? 0)}</AppText>
          <KeyValue label="This month's net sales" value={formatPaise(month.data?.netPaise ?? 0)} strong />
          <KeyValue label="Collected today (cash/UPI/card)" value={formatPaise(today.data?.collectedPaise ?? 0)} />
          <KeyValue label="Credit sales today" value={formatPaise(today.data?.creditSalesPaise ?? 0)} />
          <KeyValue label="Returns today" value={formatPaise(today.data?.returnsPaise ?? 0)} />
          <Button title="Open sales" variant="secondary" onPress={() => nav.navigate('Main', { screen: 'Sales' })} />
        </Card>
      </View>

      <AppText variant="caption" color={colors.textMuted}>
        Credit totals are what you recorded. Amounts are only shown as customer confirmed after the customer confirms them.
      </AppText>

      <View style={{ gap: spacing.sm }}>
        <Button title="New sale" onPress={() => nav.navigate('NewSale')} />
        <Button title="Add customer" variant="secondary" onPress={() => nav.navigate('AddCustomer')} />
      </View>
    </Screen>
  );
}
