import React, { useState } from 'react';
import { View } from 'react-native';
import { useQueryClient } from '@tanstack/react-query';
import { Screen } from '../../shared/components/Screen';
import { TextField } from '../../shared/components/TextField';
import { AppText, Banner, Button, Chip, ChipRow } from '../../shared/components/ui';
import { colors, spacing } from '../../core/theme';
import { createShop } from '../../core/db/repo';
import { useAuth } from '../../core/auth/AuthContext';
import { useAction } from '../../shared/hooks';
import { runSync } from '../../core/sync/engine';

const CATEGORIES = ['Kirana / Grocery', 'Medical', 'Clothing', 'Hardware', 'Dairy', 'Other'];

export function ShopSetupScreen() {
  const { user } = useAuth();
  const qc = useQueryClient();
  const [name, setName] = useState('');
  const [category, setCategory] = useState(CATEGORIES[0]);
  const [address, setAddress] = useState('');
  const [nameErr, setNameErr] = useState<string | null>(null);

  const submit = useAction(async () => {
    if (name.trim().length < 2) { setNameErr('Enter your shop name'); return; }
    setNameErr(null);
    await createShop({
      name, category, address, ownerName: user?.name ?? '', ownerMobile: user?.mobile ?? '', language: 'en',
    });
    await qc.invalidateQueries({ queryKey: ['shop'] });
    void runSync();
  });

  return (
    <Screen>
      <View style={{ gap: spacing.xs }}>
        <AppText variant="display" color={colors.primary}>Set up your shop</AppText>
        <AppText color={colors.textMuted}>This takes a minute. You can change it later.</AppText>
      </View>
      <TextField label="Shop name" value={name} onChangeText={setName} error={nameErr} />
      <View style={{ gap: spacing.sm }}>
        <AppText variant="label">Category</AppText>
        <ChipRow>
          {CATEGORIES.map((c) => <Chip key={c} label={c} selected={c === category} onPress={() => setCategory(c)} />)}
        </ChipRow>
      </View>
      <TextField label="Address / locality" value={address} onChangeText={setAddress} multiline />
      {submit.error ? <Banner tone="danger">{submit.error}</Banner> : null}
      <Button title="Create shop" loading={submit.busy} onPress={() => submit.run()} />
    </Screen>
  );
}
