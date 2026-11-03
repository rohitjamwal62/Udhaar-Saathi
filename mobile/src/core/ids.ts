import * as Crypto from 'expo-crypto';

export const newId = (): string => Crypto.randomUUID();
export const nowIso = (): string => new Date().toISOString();
