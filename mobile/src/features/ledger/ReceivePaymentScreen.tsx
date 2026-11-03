import React, { useState } from 'react';
import { useNavigation, useRoute, type RouteProp } from '@react-navigation/native';
import type { RootStackParamList } from '../../app/types';
import { Screen } from '../../shared/components/Screen';
import { TextField } from '../../shared/components/TextField';
import { AppText, Banner, Button, Chip, ChipRow, KeyValue } from '../../shared/components/ui';
import { colors } from '../../core/theme';
import { formatPaise, paiseToInput, parseRupees } from '../../core/money';
import { addPayment } from '../../core/db/repo';
import type { PayMethod } from '../../core/db/types';
import { useAction, useAfterWrite } from '../../shared/hooks';
import { resolveWhen } from '../../shared/itemsForm';
import { useCustomer } from '../../shared/queries';

const METHODS: PayMethod[] = ['cash', 'upi', 'bank', 'card', 'other'];

export function ReceivePaymentScreen() {
  const nav = useNavigation();
  const { customerId } = useRoute<RouteProp<RootStackParamList, 'ReceivePayment'>>().params;
  const customer = useCustomer(customerId);
  const afterWrite = useAfterWrite();
  const [amount, setAmount] = useState('');
  const [method, setMethod] = useState<PayMethod>('cash');
  const [reference, setReference] = useState('');
  const [when, setWhen] = useState('');
  const [note, setNote] = useState('');

  const balance = customer.data?.balance_paise ?? 0;
  const paise = parseRupees(amount);

  const submit = useAction(async () => {
    if (paise === null || paise <= 0) throw new Error('Enter a valid amount');
    const w = resolveWhen(when);
    if ('error' in w) throw new Error(w.error);
    await addPayment({ customerId, amountPaise: paise, occurredAt: w.iso, method, reference, note });
    await afterWrite();
    nav.goBack();
  });

  return (
    <Screen footer={<Button title="Record payment" loading={submit.busy} onPress={() => submit.run()} />}>
      <AppText variant="title">Payment from {customer.data?.name ?? '…'}</AppText>
      <KeyValue label="Outstanding" value={formatPaise(balance)} strong />
      <TextField label="Amount received" prefix="₹" keyboardType="decimal-pad" value={amount} onChangeText={setAmount} />
      <ChipRow>
        <Chip label="Full amount" onPress={() => setAmount(paiseToInput(balance))} />
      </ChipRow>
      <AppText variant="label">Method</AppText>
      <ChipRow>{METHODS.map((m) => <Chip key={m} label={m.toUpperCase()} selected={m === method} onPress={() => setMethod(m)} />)}</ChipRow>
      {method !== 'cash' ? <TextField label="Reference (optional)" value={reference} onChangeText={setReference} /> : null}
      <TextField label="Date (optional)" value={when} onChangeText={setWhen} placeholder="YYYY-MM-DD, blank = now" autoCapitalize="none" />
      <TextField label="Note (optional)" value={note} onChangeText={setNote} multiline />
      <AppText variant="caption" color={colors.textMuted}>
        Only record a payment you have actually received. This reduces the customer's balance; it is not counted as a new sale.
      </AppText>
      {submit.error ? <Banner tone="danger">{submit.error}</Banner> : null}
    </Screen>
  );
}
