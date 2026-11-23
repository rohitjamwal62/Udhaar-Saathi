import React, { useEffect } from 'react';
import { ActivityIndicator, View } from 'react-native';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { NavigationContainer, DefaultTheme } from '@react-navigation/native';
import { createNativeStackNavigator } from '@react-navigation/native-stack';
import { createBottomTabNavigator } from '@react-navigation/bottom-tabs';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import type { RootStackParamList, TabParamList } from './types';
import { colors, typography } from '../core/theme';
import { useAuth } from '../core/auth/AuthContext';
import { useShop } from '../shared/queries';
import { LoginScreen, SignupScreen, OtpScreen, ForgotScreen, ResetPasswordScreen } from '../features/auth/AuthScreens';
import { ShopSetupScreen } from '../features/shops/ShopSetupScreen';
import { HomeScreen } from '../features/home/HomeScreen';
import { CustomersScreen } from '../features/customers/CustomersScreen';
import { AddCustomerScreen } from '../features/customers/AddCustomerScreen';
import { CustomerDetailScreen } from '../features/customers/CustomerDetailScreen';
import { AddCreditScreen } from '../features/ledger/AddCreditScreen';
import { ReceivePaymentScreen } from '../features/ledger/ReceivePaymentScreen';
import { SalesScreen } from '../features/sales/SalesScreen';
import { NewSaleScreen } from '../features/sales/NewSaleScreen';
import { SaleDetailScreen } from '../features/sales/SaleDetailScreen';
import { ReportsScreen } from '../features/reports/ReportsScreen';
import { SettingsScreen } from '../features/settings/SettingsScreen';
import { SyncStatusScreen } from '../features/settings/SyncStatusScreen';
import { MyDuesScreen, MyDueDetailScreen, CustomerAccountScreen } from '../features/customerPortal/CustomerPortalScreens';
import { restoreFromServer } from '../core/sync/restore';
import { Button, ErrorState } from '../shared/components/ui';
import { PaymentHistoryScreen, SubscriptionScreen } from '../features/subscriptions/SubscriptionScreens';

const Stack = createNativeStackNavigator<RootStackParamList>();
const Tabs = createBottomTabNavigator<TabParamList>();

const navTheme = {
  ...DefaultTheme,
  colors: { ...DefaultTheme.colors, primary: colors.primary, background: colors.bg, card: colors.surface, text: colors.text, border: colors.border },
};

const stackHeader = {
  headerTintColor: colors.primary,
  headerTitleStyle: { ...typography.heading, color: colors.text },
  headerStyle: { backgroundColor: colors.surface },
};

function MainTabs() {
  const insets = useSafeAreaInsets();
  const { user } = useAuth();
  const alsoCustomer = !!user?.roles.includes('customer');
  return (
    <Tabs.Navigator
      screenOptions={{
        ...stackHeader,
        tabBarActiveTintColor: colors.primary,
        tabBarInactiveTintColor: colors.textMuted,
        tabBarLabelStyle: { fontSize: 12, fontWeight: '600' },
        tabBarStyle: { minHeight: 56 + insets.bottom, paddingBottom: insets.bottom },
        // Text-only tabs avoid an icon dependency; labels wrap instead of clipping on large fonts.
        tabBarIconStyle: { display: 'none' },
        tabBarLabelPosition: 'beside-icon',
      }}
    >
      <Tabs.Screen name="Home" component={HomeScreen} options={{ title: 'Home' }} />
      <Tabs.Screen name="Khata" component={CustomersScreen} options={{ title: 'Khata' }} />
      <Tabs.Screen name="Sales" component={SalesScreen} options={{ title: 'Sales' }} />
      <Tabs.Screen name="Reports" component={ReportsScreen} options={{ title: 'Reports' }} />
      {alsoCustomer ? <Tabs.Screen name="MyDues" component={MyDuesScreen} options={{ title: 'My dues' }} /> : null}
      <Tabs.Screen name="Settings" component={SettingsScreen} options={{ title: 'Settings' }} />
    </Tabs.Navigator>
  );
}

/** Customer portal: what I owe each shop. Customers have no shop, sales or sync, so this is a small app of its own. */
function CustomerTabs() {
  const insets = useSafeAreaInsets();
  return (
    <Tabs.Navigator
      screenOptions={{
        ...stackHeader,
        tabBarActiveTintColor: colors.primary,
        tabBarInactiveTintColor: colors.textMuted,
        tabBarLabelStyle: { fontSize: 12, fontWeight: '600' },
        tabBarStyle: { minHeight: 56 + insets.bottom, paddingBottom: insets.bottom },
        tabBarIconStyle: { display: 'none' },
        tabBarLabelPosition: 'beside-icon',
      }}
    >
      <Tabs.Screen name="MyDues" component={MyDuesScreen} options={{ title: 'My dues' }} />
      <Tabs.Screen name="Account" component={CustomerAccountScreen} options={{ title: 'Account' }} />
    </Tabs.Navigator>
  );
}

function Splash() {
  return (
    <View style={{ flex: 1, alignItems: 'center', justifyContent: 'center', backgroundColor: colors.bg }}>
      <ActivityIndicator size="large" color={colors.primary} />
    </View>
  );
}

function CustomerStack() {
  return (
    <Stack.Navigator screenOptions={stackHeader}>
      <Stack.Screen name="CustomerMain" component={CustomerTabs} options={{ headerShown: false }} />
      <Stack.Screen name="MyDueDetail" component={MyDueDetailScreen} options={{ title: 'Shop khata' }} />
    </Stack.Navigator>
  );
}

function ShopkeeperStack() {
  const qc = useQueryClient();
  const { user } = useAuth();
  const shop = useShop();
  // Nothing on this phone yet (fresh login / reinstall): ask the server before ever asking for the shop name again.
  const restore = useQuery({
    queryKey: ['restore', user?.id], queryFn: restoreFromServer,
    enabled: !shop.isLoading && !shop.data && !user?.demo, retry: false, staleTime: Infinity, gcTime: Infinity,
  });
  useEffect(() => {
    if (restore.data === 'restored') void qc.invalidateQueries();
  }, [restore.data, qc]);

  if (shop.isLoading) return <Splash />;
  if (!shop.data) {
    if (!user?.demo) {
      if (restore.isLoading || restore.isFetching || restore.data === 'restored') return <Splash />;
      if (restore.isError) {
        return (
          <View style={{ flex: 1, justifyContent: 'center', padding: 24, gap: 12, backgroundColor: colors.bg }}>
            <ErrorState message="We could not load your shop from the server. Check your internet connection and try again." />
            <Button title="Try again" onPress={() => void restore.refetch()} />
          </View>
        );
      }
    }
    return (
      <Stack.Navigator screenOptions={stackHeader}>
        <Stack.Screen name="ShopSetup" component={ShopSetupScreen} options={{ title: 'Your shop' }} />
      </Stack.Navigator>
    );
  }
  return (
    <Stack.Navigator screenOptions={stackHeader}>
      <Stack.Screen name="Main" component={MainTabs} options={{ headerShown: false }} />
      <Stack.Screen name="AddCustomer" component={AddCustomerScreen} options={{ title: 'Add customer' }} />
      <Stack.Screen name="CustomerDetail" component={CustomerDetailScreen} options={{ title: 'Customer' }} />
      <Stack.Screen name="AddCredit" component={AddCreditScreen} options={{ title: 'Add credit' }} />
      <Stack.Screen name="ReceivePayment" component={ReceivePaymentScreen} options={{ title: 'Receive payment' }} />
      <Stack.Screen name="NewSale" component={NewSaleScreen} options={{ title: 'New sale' }} />
      <Stack.Screen name="SaleDetail" component={SaleDetailScreen} options={{ title: 'Sale' }} />
      <Stack.Screen name="Subscription" component={SubscriptionScreen} options={{ title: 'Subscription' }} />
      <Stack.Screen name="PaymentHistory" component={PaymentHistoryScreen} options={{ title: 'Payment history' }} />
      <Stack.Screen name="SyncStatus" component={SyncStatusScreen} options={{ title: 'Sync status' }} />
      <Stack.Screen name="MyDueDetail" component={MyDueDetailScreen} options={{ title: 'Shop khata' }} />
    </Stack.Navigator>
  );
}

function SignedInStack() {
  const { user } = useAuth();
  const roles = user?.roles ?? [];
  // A person who is only a customer gets the customer portal; shopkeepers (and people who are both) get the shop app.
  if (roles.includes('customer') && !roles.includes('shopkeeper')) return <CustomerStack />;
  return <ShopkeeperStack />;
}

export function RootNavigation() {
  const { status, user } = useAuth();
  const qc = useQueryClient();
  // A different person signing in must never see the previous person's cached screens.
  useEffect(() => { qc.clear(); }, [user?.id, qc]);
  return (
    <NavigationContainer theme={navTheme}>
      {status === 'loading' ? <Splash /> : status === 'signedOut' ? (
        <Stack.Navigator screenOptions={stackHeader}>
          <Stack.Screen name="Login" component={LoginScreen} options={{ headerShown: false }} />
          <Stack.Screen name="Signup" component={SignupScreen} options={{ title: 'Create account' }} />
          <Stack.Screen name="Otp" component={OtpScreen} options={{ title: 'Verify OTP' }} />
          <Stack.Screen name="Forgot" component={ForgotScreen} options={{ title: 'Forgot password' }} />
          <Stack.Screen name="ResetPassword" component={ResetPasswordScreen} options={{ title: 'New password' }} />
        </Stack.Navigator>
      ) : (
        <SignedInStack />
      )}
    </NavigationContainer>
  );
}
