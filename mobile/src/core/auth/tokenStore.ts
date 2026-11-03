import * as SecureStore from 'expo-secure-store';
import { newId } from '../ids';

// Tokens live in the Android Keystore-backed secure store, never in plain storage.
const K = { access: 'us.access', refresh: 'us.refresh', user: 'us.user', device: 'us.device' };

export interface StoredUser {
  id: string;
  name: string;
  mobile: string;
  roles: string[];
  demo?: boolean;
}

export const tokenStore = {
  async getAccess() { return SecureStore.getItemAsync(K.access); },
  async getRefresh() { return SecureStore.getItemAsync(K.refresh); },
  async setTokens(access: string, refresh: string) {
    await SecureStore.setItemAsync(K.access, access);
    await SecureStore.setItemAsync(K.refresh, refresh);
  },
  async getUser(): Promise<StoredUser | null> {
    const raw = await SecureStore.getItemAsync(K.user);
    return raw ? (JSON.parse(raw) as StoredUser) : null;
  },
  async setUser(u: StoredUser) { await SecureStore.setItemAsync(K.user, JSON.stringify(u)); },
  async clear() {
    await Promise.all([K.access, K.refresh, K.user].map((k) => SecureStore.deleteItemAsync(k)));
  },
  async deviceId(): Promise<string> {
    let id = await SecureStore.getItemAsync(K.device);
    if (!id) {
      id = newId();
      await SecureStore.setItemAsync(K.device, id);
    }
    return id;
  },
};
