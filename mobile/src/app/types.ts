import type { NavigatorScreenParams } from '@react-navigation/native';

export type TabParamList = {
  Home: undefined;
  Khata: undefined;
  Sales: undefined;
  Reports: undefined;
  Settings: undefined;
  MyDues: undefined;
  Account: undefined;
};

export type RootStackParamList = {
  // auth
  Login: { notice?: string } | undefined;
  Signup: undefined;
  Otp: { mobile: string; challengeId: string; delivery?: 'email' | 'sms'; sentTo?: string };
  Forgot: undefined;
  ResetPassword: { mobile: string; challengeId: string; delivery?: 'email' | 'sms' };
  // onboarding
  ShopSetup: undefined;
  // app
  Main: NavigatorScreenParams<TabParamList> | undefined;
  AddCustomer: undefined;
  CustomerDetail: { customerId: string };
  AddCredit: { customerId: string };
  ReceivePayment: { customerId: string };
  NewSale: undefined;
  SaleDetail: { saleId: string };
  Subscription: undefined;
  PaymentHistory: undefined;
  SyncStatus: undefined;
  MyDueDetail: { customerId: string };
  CustomerMain: undefined;
};

declare global {
  // eslint-disable-next-line @typescript-eslint/no-namespace
  namespace ReactNavigation {
    interface RootParamList extends RootStackParamList {}
  }
}
