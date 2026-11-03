import React from 'react';
import { useQuery } from '@tanstack/react-query';
import { Screen } from '../../shared/components/Screen';
import { AppText, Badge, Banner, Button, Card, EmptyState, KeyValue } from '../../shared/components/ui';
import { colors } from '../../core/theme';
import { getDb } from '../../core/db';
import type { OutboxRow } from '../../core/db/types';
import { formatDateTime } from '../../core/dates';
import { config } from '../../core/config';
import { retryFailed, runSync } from '../../core/sync/engine';
import { useSyncState } from '../../core/sync/SyncProvider';

export function SyncStatusScreen() {
  const sync = useSyncState();
  const q = useQuery({
    queryKey: ['outbox', sync.pending, sync.failed, sync.conflict],
    queryFn: async () => (await getDb()).getAllAsync<OutboxRow>('SELECT * FROM outbox ORDER BY seq LIMIT 100'),
  });
  return (
    <Screen>
      {config.demoMode ? <Banner tone="info">Demo mode: nothing is sent to a server.</Banner> : null}
      <Card>
        <KeyValue label="Waiting to sync" value={String(sync.pending)} strong />
        <KeyValue label="Failed" value={String(sync.failed)} />
        <KeyValue label="Conflicts needing review" value={String(sync.conflict)} />
        <KeyValue label="Last successful sync" value={sync.lastSyncAt ? formatDateTime(sync.lastSyncAt) : 'Never'} />
        {sync.lastError ? <AppText variant="caption" color={colors.warning}>Last attempt: {sync.lastError}</AppText> : null}
      </Card>
      <Button title={sync.running ? 'Syncing…' : 'Sync now'} loading={sync.running} onPress={() => void runSync()} />
      {sync.failed > 0 ? <Button title="Retry failed items" variant="secondary" onPress={() => void retryFailed()} /> : null}
      {q.data?.length === 0 ? <EmptyState title="Everything is synced" /> : q.data?.map((r) => (
        <Card key={r.id}>
          <AppText variant="bodyStrong">{r.entity.replace('_', ' ')} · {r.op}</AppText>
          <Badge label={r.status} tone={r.status === 'pending' ? 'warning' : 'danger'} />
          {r.last_error ? <AppText variant="caption" color={colors.textMuted}>{r.last_error}</AppText> : null}
          <AppText variant="caption" color={colors.textMuted}>Attempts: {r.attempts}</AppText>
        </Card>
      ))}
      <AppText variant="caption" color={colors.textMuted}>
        Entries stay on this phone until the server confirms them. Nothing is deleted or overwritten while offline.
      </AppText>
    </Screen>
  );
}
