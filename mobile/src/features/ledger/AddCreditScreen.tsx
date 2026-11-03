import React, { useState } from 'react';
import { Image, View } from 'react-native';
import * as ImagePicker from 'expo-image-picker';
import { useNavigation, useRoute, type RouteProp } from '@react-navigation/native';
import type { RootStackParamList } from '../../app/types';
import { Screen } from '../../shared/components/Screen';
import { TextField } from '../../shared/components/TextField';
import { AppText, Banner, Button, Card, Chip, ChipRow, KeyValue } from '../../shared/components/ui';
import { colors, radius, spacing } from '../../core/theme';
import { formatPaise, parseRupees } from '../../core/money';
import { addCredit } from '../../core/db/repo';
import type { PayMethod } from '../../core/db/types';
import { useAction, useAfterWrite } from '../../shared/hooks';
import { emptyItem, ItemsEditor, parseItems, resolveWhen, type ItemRow } from '../../shared/itemsForm';
import { useCustomer } from '../../shared/queries';

const METHODS: PayMethod[] = ['cash', 'upi', 'card', 'bank', 'other'];

export function AddCreditScreen() {
  const nav = useNavigation();
  const { customerId } = useRoute<RouteProp<RootStackParamList, 'AddCredit'>>().params;
  const customer = useCustomer(customerId);
  const afterWrite = useAfterWrite();

  const [itemized, setItemized] = useState(true);
  const [rows, setRows] = useState<ItemRow[]>([emptyItem()]);
  const [total, setTotal] = useState('');
  const [paidNow, setPaidNow] = useState('');
  const [method, setMethod] = useState<PayMethod>('cash');
  const [when, setWhen] = useState('');
  const [note, setNote] = useState('');
  const [photo, setPhoto] = useState<string | null>(null);

  const parsed = itemized ? parseItems(rows) : null;
  const itemsTotal = parsed && 'items' in parsed ? parsed.items.reduce((s, i) => s + i.lineTotalPaise, 0) : null;
  const totalPaise = itemized ? itemsTotal : parseRupees(total);
  const paidPaise = paidNow.trim() ? parseRupees(paidNow) : 0;

  const pickPhoto = async (camera: boolean) => {
    const perm = camera ? await ImagePicker.requestCameraPermissionsAsync() : await ImagePicker.requestMediaLibraryPermissionsAsync();
    if (!perm.granted) throw new Error('Permission denied. Allow access in Android settings to attach a bill.');
    const res = camera
      ? await ImagePicker.launchCameraAsync({ quality: 0.6 })
      : await ImagePicker.launchImageLibraryAsync({ mediaTypes: ['images'], quality: 0.6 });
    if (!res.canceled) setPhoto(res.assets[0].uri);
  };
  const photoAction = useAction(pickPhoto);

  const submit = useAction(async () => {
    if (itemized && parsed && 'error' in parsed) throw new Error(parsed.error);
    if (totalPaise === null || totalPaise <= 0) throw new Error('Enter a valid amount');
    if (paidPaise === null) throw new Error('Enter a valid paid-now amount');
    const w = resolveWhen(when);
    if ('error' in w) throw new Error(w.error);
    await addCredit({
      customerId,
      occurredAt: w.iso,
      items: itemized && parsed && 'items' in parsed
        ? parsed.items.map((i) => ({
            item_name: i.itemName, quantity_milli: i.quantityMilli, unit: i.unit || null,
            unit_price_paise: i.unitPricePaise, line_total_paise: i.lineTotalPaise,
          }))
        : [],
      totalPaise,
      paidNowPaise: paidPaise,
      paidNowMethod: method,
      note,
      evidenceUri: photo,
    });
    await afterWrite();
    nav.goBack();
  });

  const remaining = totalPaise !== null && paidPaise !== null ? totalPaise - paidPaise : null;

  return (
    <Screen footer={<Button title="Save credit entry" loading={submit.busy} onPress={() => submit.run()} />}>
      <AppText variant="title">Credit for {customer.data?.name ?? '…'}</AppText>
      <ChipRow>
        <Chip label="Itemized" selected={itemized} onPress={() => setItemized(true)} />
        <Chip label="Total only" selected={!itemized} onPress={() => setItemized(false)} />
      </ChipRow>

      {itemized ? (
        <ItemsEditor rows={rows} onChange={setRows} />
      ) : (
        <>
          <TextField label="Total amount" prefix="₹" keyboardType="decimal-pad" value={total} onChangeText={setTotal} />
          <Banner tone="info">Total-only entries are labelled "Non-itemized" so the customer knows no item list was recorded.</Banner>
        </>
      )}

      <Card>
        <TextField label="Paid now (optional)" prefix="₹" keyboardType="decimal-pad" value={paidNow} onChangeText={setPaidNow}
          helper="Part of the bill the customer paid at the counter." />
        {paidPaise ? (
          <ChipRow>{METHODS.map((m) => <Chip key={m} label={m.toUpperCase()} selected={m === method} onPress={() => setMethod(m)} />)}</ChipRow>
        ) : null}
        <KeyValue label="Bill total" value={totalPaise !== null ? formatPaise(totalPaise) : '—'} />
        <KeyValue label="Goes on credit" value={remaining !== null ? formatPaise(remaining) : '—'} strong />
      </Card>

      <TextField label="Date (optional)" value={when} onChangeText={setWhen} placeholder="YYYY-MM-DD, blank = now" autoCapitalize="none" />
      <TextField label="Note (optional)" value={note} onChangeText={setNote} multiline />

      <View style={{ gap: spacing.sm }}>
        <AppText variant="label">Bill / receipt photo (optional)</AppText>
        {photo ? <Image source={{ uri: photo }} style={{ width: '100%', height: 180, borderRadius: radius.md }} resizeMode="cover" accessibilityLabel="Attached bill" /> : null}
        <ChipRow>
          <Chip label="Take photo" onPress={() => photoAction.run(true)} />
          <Chip label="Choose from gallery" onPress={() => photoAction.run(false)} />
          {photo ? <Chip label="Remove" onPress={() => setPhoto(null)} /> : null}
        </ChipRow>
        {photoAction.error ? <AppText variant="caption" color={colors.danger}>{photoAction.error}</AppText> : null}
        <AppText variant="caption" color={colors.textMuted}>
          The photo is saved on this phone and uploaded when you are online. Attaching a bill does not mean the customer has confirmed it.
        </AppText>
      </View>

      {submit.error ? <Banner tone="danger">{submit.error}</Banner> : null}
    </Screen>
  );
}
