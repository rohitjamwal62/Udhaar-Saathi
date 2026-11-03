import Constants from 'expo-constants';

const extra = (Constants.expoConfig?.extra ?? {}) as Record<string, string | undefined>;

export const config = {
  // Django backend root, e.g. https://api.example.com/api/v1  (set EXPO_PUBLIC_API_URL)
  apiUrl: process.env.EXPO_PUBLIC_API_URL ?? extra.apiUrl ?? 'http://10.0.2.2:8000/api/v1',
  // Development only: skips server auth so the offline ledger can be exercised
  // without the backend. Always false in release builds.
  demoMode: __DEV__ && process.env.EXPO_PUBLIC_DEMO_MODE === 'true',
  appVersion: Constants.expoConfig?.version ?? '1.0.0',
  androidPackage: 'com.udhaarsaathi.app',
};
