import React, { useState } from 'react';
import { FlatList, View } from 'react-native';
import { useNavigation } from '@react-navigation/native';
import type { NativeStackNavigationProp } from '@react-navigation/native-stack';
import type { RootStackParamList } from '../../app/types';
import { Screen } from '../../shared/components/Screen';
import { TextField } from '../../shared/components/TextField';
import { AppText, Button, Card, EmptyState, ErrorState, Loading, Row } from '../../shared/components/ui';
import { colors, spacing } from '../../core/theme';
import { formatPaise } from '../../core/money';
import { formatDate } from '../../core/dates';
import { useCustomers } from '../../shared/queries';

type Nav = NativeStackNavigationProp<RootStackParamList>;

export function CustomersScreen() {
  const nav = useNavigation<Nav>();
  const [search, setSearch] = useState('');
  const q = useCustomers(search);

  return (
    <Screen scroll={false}>
      <TextField label="Search customers" value={search} onChangeText={setSearch} placeholder="Name or mobile" />
      <Button title="+ Add customer" onPress={() => nav.navigate('AddCustomer')} />
      {q.isLoading ? <Loading /> : q.error ? (
        <ErrorState message={(q.error as Error).message} onRetry={() => void q.refetch()} />
      ) : (
        <FlatList
          style={{ width: '100%' }}
          data={q.data}
          keyExtractor={(c) => c.id}
          ItemSeparatorComponent={() => <View style={{ height: spacing.sm }} />}
          ListEmptyComponent={
            <EmptyState
              title={search ? 'No matching customers' : 'No customers yet'}
              body={search ? 'Try a different name or number.' : 'Add your first customer to start your khata.'}
            />
          }
          contentContainerStyle={{ paddingBottom: spacing.xxl }}
          renderItem={({ item }) => (
            <Card>
              <Row
                onPress={() => nav.navigate('CustomerDetail', { customerId: item.id })}
                left={
                  <View>
                    <AppText variant="bodyStrong">{item.name}</AppText>
                    <AppText variant="caption" color={colors.textMuted}>
                      {item.mobile ?? 'No phone'}{item.last_activity_at ? ` · last ${formatDate(item.last_activity_at)}` : ''}
                    </AppText>
                  </View>
                }
                right={
                  <View style={{ alignItems: 'flex-end' }}>
                    <AppText variant="bodyStrong" color={item.balance_paise > 0 ? colors.danger : item.balance_paise < 0 ? colors.success : colors.textMuted}>
                      {formatPaise(Math.abs(item.balance_paise))}
                    </AppText>
                    <AppText variant="caption" color={colors.textMuted}>
                      {item.balance_paise > 0 ? 'to collect' : item.balance_paise < 0 ? 'advance' : 'settled'}
                    </AppText>
                  </View>
                }
              />
            </Card>
          )}
        />
      )}
    </Screen>
  );
}
