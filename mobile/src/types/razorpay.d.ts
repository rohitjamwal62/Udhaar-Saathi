declare module 'react-native-razorpay' {
  export interface RazorpayOptions {
    key: string;
    order_id: string;
    amount: number; // paise
    currency: string;
    name: string;
    description?: string;
    prefill?: { contact?: string; name?: string; email?: string };
    theme?: { color?: string };
  }
  export interface RazorpaySuccess {
    razorpay_payment_id: string;
    razorpay_order_id: string;
    razorpay_signature: string;
  }
  const RazorpayCheckout: { open(options: RazorpayOptions): Promise<RazorpaySuccess> };
  export default RazorpayCheckout;
}
