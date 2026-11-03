import React from 'react';
import { StatusBar } from 'expo-status-bar';
import { SafeAreaProvider } from 'react-native-safe-area-context';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { AuthProvider, useAuth } from './src/core/auth/AuthContext';
import { SyncProvider } from './src/core/sync/SyncProvider';
import { RootNavigation } from './src/app/navigation';
import { UpdatePrompt } from './src/app/UpdatePrompt';
import { warmUpServer } from './src/core/api/client';

warmUpServer();

const queryClient = new QueryClient({
  defaultOptions: { queries: { staleTime: 0, retry: false } },
});

function Shell() {
  const { status, user } = useAuth();
  return (
    <>
      <RootNavigation />
      {/* Re-checks for updates at launch and again after login. */}
      <UpdatePrompt refreshKey={`${status}:${user?.id ?? ''}`} />
    </>
  );
}

export default function App() {
  return (
    <SafeAreaProvider>
      <QueryClientProvider client={queryClient}>
        <AuthProvider>
          <SyncProvider>
            <Shell />
          </SyncProvider>
        </AuthProvider>
      </QueryClientProvider>
      <StatusBar style="dark" />
    </SafeAreaProvider>
  );
}
