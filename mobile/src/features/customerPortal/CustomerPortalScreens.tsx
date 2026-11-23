import React from 'react';
import { Alert, FlatList, RefreshControl, View } from 'react-native';
import { useQuery } from '@tanstack/react-query';
import { useNavigation } from '@react-navigation/native';
import type { NativeStackNavigationProp, NativeStackScreenProps } from '@react-navigation/native-stack';
import type { RootStackParamList } from '../../app/types';
import { Screen } from '../../shared/components/Screen';
import { AppText, Badge, Banner, Button, Card, EmptyState, ErrorState, KeyValue, Loading, Row } from '../../shared/components/ui';
import { colors, spacing } from '../../core/theme';
import { formatPaise } from '../../core/money';
import { formatDate, formatDateTime } from '../../core/dates';
import { api } from '../../core/api/client';
import { config } from '../../core/config';
import { useAuth } from '../../core/auth/AuthContext';

interface MyShop {
  customer_id: string; shop_name: string; shop_address: string | null; owner_name: string; owner_mobile: string;
  balance_paise: number; last_activity_at: string | null;
}
interface MyEvent {
  id: string; type: string; amount_paise: number; delta_paise: number; occurred_at: string; note: string | null;
  running_balance_paise: number; reversal_of_id: string | null; confirmation_status: string;
  items: { item_name: string; line_total_paise: number }[];
}
interface MyDetail { balance_paise: number; shop_name: string; owner_name: string; owner_mobile: string; events: MyEvent[] }

const useMyKhata = () =>
  useQuery({ queryKey: ['myKhata'], queryFn: () => api<{ total_owed_paise: number; results: MyShop[] }>('/me/khata') });

/** Customer portal home: every shop that has this person on its khata, and what is owed to each. */
export function MyDuesScreen() {
  const nav = useNavigation<NativeStackNavigationProp<RootStackParamList>>();
  const { user } = useAuth();
  const q = useMyKhata();
  if (q.isLoading) return <Screen scroll={false}><Loading /></Screen>;
  if (q.error) return <Screen scroll={false}><ErrorState message={(q.error as Error).message} onRetry={() => void q.refetch()} /></Screen>;
  const list = q.data?.results ?? [];
  const owed = q.data?.total_owed_paise ?? 0;
  return (
    <Screen scroll={false}>
      <Card>
        <AppText variant="caption" color={colors.textMuted}>Total you owe</AppText>
        <AppText variant="display" color={owed > 0 ? colors.danger : colors.success}>{formatPaise(owed)}</AppText>
      </Card>
      <FlatList
        style={{ width: '100%' }}
        data={list}
        keyExtractor={(x) => x.customer_id}
        refreshControl={<RefreshControl refreshing={q.isRefetching} onRefresh={() => void q.refetch()} />}
        ItemSeparatorComponent={() => <View style={{ height: spacing.sm }} />}
        contentContainerStyle={{ paddingBottom: spacing.xxl }}
        ListEmptyComponent={
          <EmptyState title="No shop has added you yet"
            body={`When a shopkeeper adds your mobile number (${user?.mobile ?? ''}) to their khata, the shop and what you owe appears here.`} />
        }
        renderItem={({ item }) => (
          <Card>
            <Row
              onPress={() => nav.navigate('MyDueDetail', { customerId: item.customer_id })}
              left={(
                <View>
                  <AppText variant="bodyStrong">{item.shop_name}</AppText>
                  <AppText variant="caption" color={colors.textMuted}>
                    {item.owner_name}{item.last_activity_at ? ` · last ${formatDate(item.last_activity_at)}` : ''}
                  </AppText>
                </View>
              )}
              right={(
                <View style={{ alignItems: 'flex-end' }}>
                  <AppText variant="bodyStrong" color={item.balance_paise > 0 ? colors.danger : colors.success}>
                    {formatPaise(Math.abs(item.balance_paise))}
                  </AppText>
                  <AppText variant="caption" color={colors.textMuted}>
                    {item.balance_paise > 0 ? 'you owe' : item.balance_paise < 0 ? 'advance' : 'settled'}
                  </AppText>
                </View>
              )}
            />
          </Card>
        )}
      />
    </Screen>
  );
}

const LABEL: Record<string, string> = {
  opening: 'Opening balance', credit: 'Taken on credit', payment: 'You paid', adjustment: 'Adjustment', reversal: 'Entry reversed',
};

export function MyDueDetailScreen({ route }: NativeStackScreenProps<RootStackParamList, 'MyDueDetail'>) {
  const { customerId } = route.params;
  const q = useQuery({ queryKey: ['myKhata', customerId], queryFn: () => api<MyDetail>(`/me/khata/${customerId}`) });
  if (q.isLoading) return <Screen scroll={false}><Loading /></Screen>;
  if (q.error || !q.data) {
    return <Screen scroll={false}><ErrorState message={(q.error as Error)?.message ?? 'Not found'} onRetry={() => void q.refetch()} /></Screen>;
  }
  const d = q.data;
  const events = [...d.events].reverse();
  return (
    <Screen>
      <Card>
        <AppText variant="heading">{d.shop_name}</AppText>
        <KeyValue label="Shopkeeper" value={d.owner_name} />
        <KeyValue label="Phone" value={d.owner_mobile} />
        <KeyValue label={d.balance_paise >= 0 ? 'You owe' : 'Advance with shop'} value={formatPaise(Math.abs(d.balance_paise))} strong />
      </Card>
      <Banner tone="info">This is the shopkeeper's record. If something looks wrong, speak to the shop.</Banner>
      {events.length === 0 ? <EmptyState title="No entries yet" /> : events.map((e) => (
        <Card key={e.id}>
          <Row
            left={(
              <View>
                <AppText variant="bodyStrong">{LABEL[e.type] ?? e.type}</AppText>
                <AppText variant="caption" color={colors.textMuted}>{formatDateTime(e.occurred_at)}</AppText>
                {e.note ? <AppText variant="caption">{e.note}</AppText> : null}
                {e.items.map((i, k) => (
                  <AppText key={k} variant="caption" color={colors.textMuted}>{i.item_name} · {formatPaise(i.line_total_paise)}</AppText>
                ))}
              </View>
            )}
            right={(
              <View style={{ alignItems: 'flex-end' }}>
                <AppText variant="bodyStrong" color={e.delta_paise > 0 ? colors.danger : colors.success}>
                  {e.delta_paise > 0 ? '+' : e.delta_paise < 0 ? '-' : ''}{formatPaise(Math.abs(e.delta_paise))}
                </AppText>
                <AppText variant="caption" color={colors.textMuted}>Balance {formatPaise(e.running_balance_paise)}</AppText>
                {e.confirmation_status === 'customer_confirmed' ? <Badge label="Confirmed" tone="success" /> : null}
              </View>
            )}
          />
        </Card>
      ))}
    </Screen>
  );
}

/** Account tab for customers (they have no shop settings). */
export function CustomerAccountScreen() {
  const { user, signOut } = useAuth();
  return (
    <Screen>
      <Card>
        <AppText variant="heading">Account</AppText>
        <KeyValue label="Name" value={user?.name ?? '-'} />
        <KeyValue label="Mobile" value={user?.mobile ?? '-'} />
        <KeyValue label="Type" value="Customer" />
      </Card>
      <Button
        title="Log out" variant="danger"
        onPress={() => Alert.alert('Log out?', 'You will need to log in again.', [
          { text: 'Cancel', style: 'cancel' }, { text: 'Log out', style: 'destructive', onPress: () => void signOut() }])}
      />
      <AppText variant="caption" color={colors.textMuted} center>LenDen Saathi v{config.appVersion}</AppText>
    </Screen>
  );
}
