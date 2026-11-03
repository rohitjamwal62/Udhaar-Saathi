import React, { useState } from 'react';
import { View } from 'react-native';
import { useNavigation } from '@react-navigation/native';
import { Screen } from '../../shared/components/Screen';
import { TextField } from '../../shared/components/TextField';
import { AppText, Banner, Button, Card, Chip, ChipRow, KeyValue } from '../../shared/components/ui';
import { colors, spacing } from '../../core/theme';
import { formatPaise, parseRupees } from '../../core/money';
import { computeSaleTotals, createSale } from '../../core/db/repo';
import type { SalePayMethod } from '../../core/db/types';
import { newId } from '../../core/ids';
import { useAction, useAfterWrite } from '../../shared/hooks';
import { emptyItem, ItemsEditor, parseItems, resolveWhen, type ItemRow } from '../../shared/itemsForm';
import { useCustomers } from '../../shared/queries';

const METHODS: SalePayMethod[] = ['cash', 'upi', 'card', 'bank', 'other', 'credit'];
const LABEL = (m: SalePayMethod) => (m === 'credit' ? 'KHATA (credit)' : m.toUpperCase());

interface PayRow { key: string; method: SalePayMethod; amount: string }

export function NewSaleScreen() {
  const nav = useNavigation();
  const afterWrite = useAfterWrite();
  const [itemized, setItemized] = useState(false);
  const [rows, setRows] = useState<ItemRow[]>([emptyItem()]);
  const [quickTotal, setQuickTotal] = useState('');
  const [billDiscount, setBillDiscount] = useState('');
  const [pays, setPays] = useState<PayRow[]>([{ key: newId(), method: 'cash', amount: '' }]);
  const [customerId, setCustomerId] = useState<string | null>(null);
  const [search, setSearch] = useState('');
  const [choosing, setChoosing] = useState(false);
  const [when, setWhen] = useState('');
  const [note, setNote] = useState('');
  const customers = useCustomers(search);

  const parsed = itemized ? parseItems(rows) : null;
  const items = parsed && 'items' in parsed ? parsed.items : [];
  const quickPaise = parseRupees(quickTotal);
  const billDisc = billDiscount.trim() ? parseRupees(billDiscount) : 0;
  const totals = computeSaleTotals({
    items, quickTotalPaise: itemized ? 0 : quickPaise ?? 0, billDiscountPaise: billDisc ?? 0,
  });
  const paid = pays.reduce((s, p) => s + (parseRupees(p.amount) ?? 0), 0);
  const hasCredit = pays.some((p) => p.method === 'credit');
  const chosen = customers.data?.find((c) => c.id === customerId);

  const submit = useAction(async () => {
    if (itemized && parsed && 'error' in parsed) throw new Error(parsed.error);
    if (!itemized && (quickPaise === null || quickPaise <= 0)) throw new Error('Enter the sale amount');
    if (billDisc === null) throw new Error('Invalid discount');
    const w = resolveWhen(when);
    if ('error' in w) throw new Error(w.error);

    // A single payment row with no amount means "the full payable amount".
    const payments = pays.map((p) => ({
      method: p.method,
      amountPaise: pays.length === 1 && !p.amount.trim() ? totals.payable : parseRupees(p.amount) ?? NaN,
      reference: '',
    }));
    if (payments.some((p) => Number.isNaN(p.amountPaise) || p.amountPaise <= 0)) throw new Error('Enter a valid amount for every payment');

    await createSale({
      customerId, saleAt: w.iso, items, quickTotalPaise: quickPaise ?? 0,
      billDiscountPaise: billDisc, payments, note,
    });
    await afterWrite();
    nav.goBack();
  });

  const setPay = (key: string, patch: Partial<PayRow>) => setPays(pays.map((p) => (p.key === key ? { ...p, ...patch } : p)));

  return (
    <Screen footer={<Button title="Save sale" loading={submit.busy} onPress={() => submit.run()} />}>
      <ChipRow>
        <Chip label="Quick sale" selected={!itemized} onPress={() => setItemized(false)} />
        <Chip label="Itemized sale" selected={itemized} onPress={() => setItemized(true)} />
      </ChipRow>

      {itemized ? (
        <ItemsEditor rows={rows} onChange={setRows} allowDiscount />
      ) : (
        <TextField label="Sale amount" prefix="₹" keyboardType="decimal-pad" value={quickTotal} onChangeText={setQuickTotal} />
      )}
      <TextField label="Bill discount (optional)" prefix="₹" keyboardType="decimal-pad" value={billDiscount} onChangeText={setBillDiscount} />

      <Card>
        <KeyValue label="Gross" value={formatPaise(totals.gross)} />
        <KeyValue label="Discount" value={`− ${formatPaise(totals.discount)}`} />
        <KeyValue label="Amount payable" value={formatPaise(totals.payable)} strong />
      </Card>

      <View style={{ gap: spacing.sm }}>
        <AppText variant="heading">Payment</AppText>
        {pays.map((p) => (
          <Card key={p.key}>
            <ChipRow>{METHODS.map((m) => <Chip key={m} label={LABEL(m)} selected={p.method === m} onPress={() => setPay(p.key, { method: m })} />)}</ChipRow>
            <TextField label="Amount" prefix="₹" keyboardType="decimal-pad" value={p.amount}
              placeholder={pays.length === 1 ? 'Blank = full amount' : ''} onChangeText={(t) => setPay(p.key, { amount: t })} />
            {pays.length > 1 ? <Button title="Remove" variant="ghost" onPress={() => setPays(pays.filter((x) => x.key !== p.key))} /> : null}
          </Card>
        ))}
        <Button title="+ Split payment" variant="secondary" onPress={() => setPays([...pays, { key: newId(), method: 'upi', amount: '' }])} />
        {pays.length > 1 ? (
          <KeyValue label="Entered / payable" value={`${formatPaise(paid)} / ${formatPaise(totals.payable)}`} strong />
        ) : null}
      </View>

      <View style={{ gap: spacing.sm }}>
        <AppText variant="heading">Customer {hasCredit ? '(required for credit)' : '(optional)'}</AppText>
        {chosen ? (
          <Card>
            <AppText variant="bodyStrong">{chosen.name}</AppText>
            <Button title="Change / remove" variant="ghost" onPress={() => { setCustomerId(null); setChoosing(true); }} />
          </Card>
        ) : choosing || hasCredit ? (
          <Card>
            <TextField label="Search customer" value={search} onChangeText={setSearch} />
            {customers.data?.slice(0, 8).map((c) => (
              <Button key={c.id} title={c.name} variant="secondary" onPress={() => { setCustomerId(c.id); setChoosing(false); }} />
            ))}
            {customers.data?.length === 0 ? <AppText color={colors.textMuted}>No match. Add the customer from the Khata tab first.</AppText> : null}
          </Card>
        ) : (
          <Button title="Link a customer" variant="secondary" onPress={() => setChoosing(true)} />
        )}
        {hasCredit ? (
          <Banner tone="info">The credit portion is added to this customer's khata as one linked entry. A cash sale never creates a debt.</Banner>
        ) : null}
      </View>

      <TextField label="Date (optional)" value={when} onChangeText={setWhen} placeholder="YYYY-MM-DD, blank = now" autoCapitalize="none" />
      <TextField label="Note (optional)" value={note} onChangeText={setNote} multiline />
      {submit.error ? <Banner tone="danger">{submit.error}</Banner> : null}
    </Screen>
  );
}
