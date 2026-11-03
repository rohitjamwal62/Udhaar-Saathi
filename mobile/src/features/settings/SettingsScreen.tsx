import React from 'react';
import { Alert } from 'react-native';
import { useNavigation } from '@react-navigation/native';
import type { NativeStackNavigationProp } from '@react-navigation/native-stack';
import type { RootStackParamList } from '../../app/types';
import { Screen } from '../../shared/components/Screen';
import { AppText, Button, Card, KeyValue } from '../../shared/components/ui';
import { colors } from '../../core/theme';
import { config } from '../../core/config';
import { useAuth } from '../../core/auth/AuthContext';
import { useShop } from '../../shared/queries';
import { useSyncState } from '../../core/sync/SyncProvider';

type Nav = NativeStackNavigationProp<RootStackParamList>;

export function SettingsScreen() {
  const nav = useNavigation<Nav>();
  const { user, signOut } = useAuth();
  const shop = useShop();
  const sync = useSyncState();
  const unsynced = sync.pending + sync.failed + sync.conflict;

  const confirmLogout = () =>
    Alert.alert(
      'Log out?',
      unsynced > 0
        ? `${unsynced} entries have not synced yet. Logging out removes them from this phone and they will be lost. Connect to the internet and sync first.`
        : 'You will need to log in again.',
      [{ text: 'Cancel', style: 'cancel' }, { text: unsynced ? 'Log out and lose entries' : 'Log out', style: 'destructive', onPress: () => void signOut() }],
    );

  return (
    <Screen>
      <Card>
        <AppText variant="heading">Account</AppText>
        <KeyValue label="Name" value={user?.name ?? '-'} />
        <KeyValue label="Mobile" value={user?.mobile ?? '-'} />
      </Card>
      <Card>
        <AppText variant="heading">Shop</AppText>
        <KeyValue label="Name" value={shop.data?.name ?? '-'} />
        <KeyValue label="Category" value={shop.data?.category ?? '-'} />
        <KeyValue label="Address" value={shop.data?.address ?? '-'} />
      </Card>
      <Button title="Subscription and payments" variant="secondary" onPress={() => nav.navigate('Subscription')} />
      <Button title={unsynced ? `Sync status (${unsynced} waiting)` : 'Sync status'} variant="secondary" onPress={() => nav.navigate('SyncStatus')} />
      <Button title="Log out" variant="danger" onPress={confirmLogout} />
      <AppText variant="caption" color={colors.textMuted} center>
        UdhaarSaathi v{config.appVersion}{config.demoMode ? ' · DEMO MODE' : ''}
      </AppText>
    </Screen>
  );
}
