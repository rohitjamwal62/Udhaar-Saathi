import React, { useEffect, useSyncExternalStore } from 'react';
import { AppState } from 'react-native';
import * as Network from 'expo-network';
import { useQueryClient } from '@tanstack/react-query';
import { refreshCounts, runSync, syncStore } from './engine';

export function useSyncState() {
  return useSyncExternalStore(syncStore.subscribe, syncStore.getSnapshot);
}

/** Triggers sync on start, resume, connectivity regained and every minute while foregrounded. */
export function SyncProvider({ children }: { children: React.ReactNode }) {
  const qc = useQueryClient();
  useEffect(() => {
    const go = () => { void runSync().then(() => qc.invalidateQueries()); };
    void refreshCounts();
    go();
    const appSub = AppState.addEventListener('change', (s) => { if (s === 'active') go(); });
    const netSub = Network.addNetworkStateListener((s) => {
      if (s.isConnected && s.isInternetReachable !== false) go();
    });
    const timer = setInterval(go, 60_000);
    return () => { appSub.remove(); netSub.remove(); clearInterval(timer); };
  }, [qc]);
  return <>{children}</>;
}
