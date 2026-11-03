import React, { useState } from 'react';
import { Alert } from 'react-native';
import { useNavigation } from '@react-navigation/native';
import { Screen } from '../../shared/components/Screen';
import { TextField } from '../../shared/components/TextField';
import { Banner, Button } from '../../shared/components/ui';
import { addCustomer, findDuplicateCustomers } from '../../core/db/repo';
import { parseRupees } from '../../core/money';
import { useAction, useAfterWrite } from '../../shared/hooks';
import { normalizeMobile } from '../auth/validation';

export function AddCustomerScreen() {
  const nav = useNavigation();
  const afterWrite = useAfterWrite();
  const [name, setName] = useState('');
  const [mobile, setMobile] = useState('');
  const [opening, setOpening] = useState('');
  const [notes, setNotes] = useState('');
  const [errs, setErrs] = useState<Record<string, string>>({});

  const save = async () => {
    const m = mobile.trim() ? normalizeMobile(mobile) : '';
    const openingPaise = opening.trim() ? parseRupees(opening) : 0;
    await addCustomer({ name, mobile: m ?? '', notes, openingBalancePaise: openingPaise ?? 0 });
    await afterWrite();
    nav.goBack();
  };

  const submit = useAction(async () => {
    const e: Record<string, string> = {};
    if (!name.trim()) e.name = 'Enter the customer name';
    if (mobile.trim() && !normalizeMobile(mobile)) e.mobile = 'Enter a valid 10-digit mobile number';
    if (opening.trim() && parseRupees(opening) === null) e.opening = 'Enter a valid amount';
    setErrs(e);
    if (Object.keys(e).length) return;

    // Warn about possible duplicates, but never merge automatically.
    const dups = await findDuplicateCustomers(name, normalizeMobile(mobile) ?? '');
    if (dups.length) {
      Alert.alert(
        'Possible duplicate',
        `${dups.map((d) => d.name).join(', ')} already exists with the same name or phone number. Add this as a separate customer?`,
        [{ text: 'Cancel', style: 'cancel' }, { text: 'Add anyway', onPress: () => void save() }],
      );
      return;
    }
    await save();
  });

  return (
    <Screen footer={<Button title="Save customer" loading={submit.busy} onPress={() => submit.run()} />}>
      <TextField label="Customer name" value={name} onChangeText={setName} error={errs.name} />
      <TextField label="Mobile number (optional)" prefix="+91" keyboardType="phone-pad" value={mobile} onChangeText={setMobile}
        error={errs.mobile} maxLength={13} helper="Needed later to invite the customer to confirm entries." />
      <TextField label="Opening balance (optional)" prefix="₹" keyboardType="decimal-pad" value={opening} onChangeText={setOpening}
        error={errs.opening} helper="Existing dues from your paper khata. Recorded as a labelled opening-balance entry." />
      <TextField label="Notes (optional)" value={notes} onChangeText={setNotes} multiline />
      {submit.error ? <Banner tone="danger">{submit.error}</Banner> : null}
    </Screen>
  );
}
