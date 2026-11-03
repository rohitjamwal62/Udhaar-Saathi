import type { CheckoutOrder } from '../../core/api/endpoints';

export interface CheckoutResult {
  paymentId: string;
  orderId: string;
  signature: string;
}

/**
 * Opens Razorpay Checkout for an order that the Django server already created.
 * Only the public key id is used here; the secret key never ships in the app.
 * The native module is loaded lazily so the rest of the app still runs in a
 * build/preview where the module is unavailable (e.g. Expo Go).
 * The returned signature MUST be verified by the server before access is granted.
 */
export async function openCheckout(
  order: CheckoutOrder,
  prefill: { contact?: string; name?: string },
): Promise<CheckoutResult> {
  let Razorpay: typeof import('react-native-razorpay').default;
  try {
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    Razorpay = require('react-native-razorpay').default;
  } catch {
    throw new Error('Payments need the installed app build (not Expo Go). Use a development or release build.');
  }
  if (!Razorpay?.open) throw new Error('Payment module is not available in this build.');
  try {
    const r = await Razorpay.open({
      key: order.key_id,
      order_id: order.order_id,
      amount: order.amount_paise,
      currency: order.currency,
      name: 'UdhaarSaathi',
      description: 'UdhaarSaathi monthly subscription',
      prefill,
      theme: { color: '#0B6E4F' },
    });
    return { paymentId: r.razorpay_payment_id, orderId: r.razorpay_order_id, signature: r.razorpay_signature };
  } catch (e) {
    const err = e as { description?: string; message?: string };
    throw new Error(err.description ?? err.message ?? 'Payment was cancelled or failed.');
  }
}
