import React, { useEffect, useSyncExternalStore } from 'react';
import { AppState } from 'react-native';
import * as Network from 'expo-network';
import { useQueryClient } from '@tanstack/react-query';
import { refreshCounts, runSync, syncNow, syncStore } from './engine';

export function useSyncState() {
  return useSyncExternalStore(syncStore.subscribe, syncStore.getSnapshot);
}

/** Triggers sync on start, resume, connectivity regained and every minute while foregrounded. */
export function SyncProvider({ children }: { children: React.ReactNode }) {
  const qc = useQueryClient();
  useEffect(() => {
    const go = () => { void runSync().then(() => qc.invalidateQueries()); };
    const goNow = () => { void syncNow().then(() => qc.invalidateQueries()); };   // connection back / app resumed: skip the waiting time
    void refreshCounts();
    go();
    const appSub = AppState.addEventListener('change', (s) => { if (s === 'active') goNow(); });
    const netSub = Network.addNetworkStateListener((s) => {
      if (s.isConnected && s.isInternetReachable !== false) goNow();
    });
    const timer = setInterval(go, 60_000);
    return () => { appSub.remove(); netSub.remove(); clearInterval(timer); };
  }, [qc]);
  return <>{children}</>;
}
