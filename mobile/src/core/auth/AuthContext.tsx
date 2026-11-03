import React, { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import { authApi, type AuthSession } from '../api/endpoints';
import { setSessionExpiredHandler } from '../api/client';
import { tokenStore, type StoredUser } from './tokenStore';
import { resetDb } from '../db';
import { config } from '../config';
import { newId } from '../ids';

type Status = 'loading' | 'signedOut' | 'signedIn';

interface AuthValue {
  status: Status;
  user: StoredUser | null;
  signIn(session: AuthSession): Promise<void>;
  login(mobile: string, password: string): Promise<void>;
  signOut(): Promise<void>;
  signInDemo(): Promise<void>;
}

const Ctx = createContext<AuthValue | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [status, setStatus] = useState<Status>('loading');
  const [user, setUser] = useState<StoredUser | null>(null);

  const signIn = useCallback(async (s: AuthSession) => {
    await tokenStore.setTokens(s.access, s.refresh);
    await tokenStore.setUser(s.user);
    setUser(s.user);
    setStatus('signedIn');
  }, []);

  const login = useCallback(async (mobile: string, password: string) => {
    const s = await authApi.login({ mobile, password, device_id: await tokenStore.deviceId() });
    await signIn(s);
  }, [signIn]);

  const signOut = useCallback(async () => {
    try { if (!user?.demo) await authApi.logout(); } catch { /* best effort; clear locally anyway */ }
    await tokenStore.clear();
    // The local DB belongs to the signed-in account. Settings warns about unsynced items first.
    await resetDb();
    setUser(null);
    setStatus('signedOut');
  }, [user]);

  const signInDemo = useCallback(async () => {
    if (!config.demoMode) return;
    const u: StoredUser = {
      id: newId(), name: 'Demo Shopkeeper', mobile: '+910000000000', roles: ['shopkeeper'], demo: true,
    };
    await tokenStore.setUser(u);
    setUser(u);
    setStatus('signedIn');
  }, []);

  useEffect(() => {
    setSessionExpiredHandler(() => {
      void tokenStore.clear().then(() => { setUser(null); setStatus('signedOut'); });
    });
    (async () => {
      const [u, access] = await Promise.all([tokenStore.getUser(), tokenStore.getAccess()]);
      if (u && (access || u.demo)) { setUser(u); setStatus('signedIn'); } else setStatus('signedOut');
    })();
  }, []);

  const value = useMemo(
    () => ({ status, user, signIn, login, signOut, signInDemo }),
    [status, user, signIn, login, signOut, signInDemo],
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useAuth(): AuthValue {
  const v = useContext(Ctx);
  if (!v) throw new Error('useAuth outside AuthProvider');
  return v;
}
