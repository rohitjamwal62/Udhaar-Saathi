import React, { useEffect, useState } from 'react';
import { Linking, Modal, StyleSheet, View } from 'react-native';
import { useQuery } from '@tanstack/react-query';
import { appApi } from '../core/api/endpoints';
import { decideUpdate } from '../core/appUpdate';
import { config } from '../core/config';
import { colors, radius, spacing } from '../core/theme';
import { AppText, Button } from '../shared/components/ui';

/**
 * Server-controlled update prompt. Shown at launch (and when the user logs in, since this
 * mounts again). Optional updates can be dismissed; required ones block the app.
 * Updates always go through the official Play Store listing, never a downloaded APK.
 */
export function UpdatePrompt({ refreshKey }: { refreshKey: string }) {
  const [dismissed, setDismissed] = useState(false);
  const q = useQuery({
    queryKey: ['appConfig', refreshKey],
    queryFn: appApi.config,
    enabled: !config.demoMode,
    retry: false,
    staleTime: 60 * 60 * 1000,
  });
  useEffect(() => setDismissed(false), [refreshKey]);

  if (!q.data) return null;
  const decision = decideUpdate(config.appVersion, q.data);
  if (decision === 'none' || (decision === 'optional' && dismissed)) return null;

  const openStore = async () => {
    const market = `market://details?id=${config.androidPackage}`;
    try { await Linking.openURL(market); } catch {
      await Linking.openURL(`https://play.google.com/store/apps/details?id=${config.androidPackage}`);
    }
  };

  return (
    <Modal visible transparent animationType="fade" onRequestClose={() => { if (decision === 'optional') setDismissed(true); }}>
      <View style={styles.backdrop}>
        <View style={styles.sheet} accessibilityViewIsModal>
          <AppText variant="title">{decision === 'required' ? 'Update required' : 'Update available'}</AppText>
          <AppText color={colors.textMuted}>
            {q.data.message ?? (decision === 'required'
              ? 'This version is no longer supported. Please update to keep using LenDen Saathi. Your data is safe.'
              : 'A new version of LenDen Saathi is available with improvements and fixes.')}
          </AppText>
          <Button title="Update now" onPress={() => void openStore()} />
          {decision === 'optional' ? <Button title="Later" variant="ghost" onPress={() => setDismissed(true)} /> : null}
        </View>
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  backdrop: { flex: 1, backgroundColor: 'rgba(0,0,0,0.5)', justifyContent: 'center', padding: spacing.lg },
  sheet: {
    backgroundColor: colors.surface, borderRadius: radius.lg, padding: spacing.lg, gap: spacing.md,
    width: '100%', maxWidth: 480, alignSelf: 'center',
  },
});
