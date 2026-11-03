import { useCallback, useState } from 'react';
import { useWindowDimensions } from 'react-native';
import { useQueryClient } from '@tanstack/react-query';
import { breakpoints } from '../core/theme';
import { runSync } from '../core/sync/engine';

/** Compact phones stack content; wider windows (large phones landscape / tablets) go side by side. */
export function useIsRegular(): boolean {
  const { width } = useWindowDimensions();
  return width >= breakpoints.regular;
}

/** Wraps an async handler with busy + error state for forms. */
export function useAction<A extends unknown[]>(fn: (...args: A) => Promise<void>) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const run = useCallback(
    async (...args: A) => {
      setBusy(true);
      setError(null);
      try {
        await fn(...args);
      } catch (e) {
        setError(e instanceof Error ? e.message : 'Something went wrong');
      } finally {
        setBusy(false);
      }
    },
    [fn],
  );
  return { run, busy, error, setError };
}

/** Call after any local write: refresh every cached read and try to sync right away. */
export function useAfterWrite() {
  const qc = useQueryClient();
  return useCallback(async () => {
    await qc.invalidateQueries();
    void runSync().then(() => qc.invalidateQueries());
  }, [qc]);
}
