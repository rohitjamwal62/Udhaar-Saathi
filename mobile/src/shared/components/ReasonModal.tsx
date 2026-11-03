import React, { useEffect, useState } from 'react';
import { Modal, Pressable, StyleSheet, View } from 'react-native';
import { colors, radius, spacing } from '../../core/theme';
import { AppText, Banner, Button } from './ui';
import { TextField } from './TextField';

interface Props {
  visible: boolean;
  title: string;
  description?: string;
  confirmLabel: string;
  onCancel: () => void;
  onConfirm: (reason: string) => Promise<void>;
}

/** Prompts for a mandatory reason before a correction (reversal) is posted. */
export function ReasonModal({ visible, title, description, confirmLabel, onCancel, onConfirm }: Props) {
  const [reason, setReason] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => { if (visible) { setReason(''); setError(null); } }, [visible]);

  const confirm = async () => {
    if (!reason.trim()) { setError('A reason is required'); return; }
    setBusy(true);
    setError(null);
    try { await onConfirm(reason.trim()); } catch (e) { setError(e instanceof Error ? e.message : 'Failed'); } finally { setBusy(false); }
  };

  return (
    <Modal visible={visible} transparent animationType="fade" onRequestClose={onCancel}>
      <Pressable style={styles.backdrop} onPress={onCancel}>
        <Pressable style={styles.sheet} onPress={() => undefined}>
          <AppText variant="heading">{title}</AppText>
          {description ? <AppText color={colors.textMuted}>{description}</AppText> : null}
          <TextField label="Reason" value={reason} onChangeText={setReason} multiline />
          {error ? <Banner tone="danger">{error}</Banner> : null}
          <View style={{ gap: spacing.sm }}>
            <Button title={confirmLabel} variant="danger" loading={busy} onPress={confirm} />
            <Button title="Cancel" variant="ghost" onPress={onCancel} />
          </View>
        </Pressable>
      </Pressable>
    </Modal>
  );
}

const styles = StyleSheet.create({
  backdrop: { flex: 1, backgroundColor: 'rgba(0,0,0,0.4)', justifyContent: 'center', padding: spacing.lg },
  sheet: {
    backgroundColor: colors.surface, borderRadius: radius.lg, padding: spacing.lg, gap: spacing.md,
    width: '100%', maxWidth: 480, alignSelf: 'center',
  },
});
