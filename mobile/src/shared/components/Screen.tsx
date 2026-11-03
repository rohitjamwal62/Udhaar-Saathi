import React from 'react';
import { KeyboardAvoidingView, Platform, ScrollView, StyleSheet, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { colors, sizes, spacing } from '../../core/theme';

interface Props {
  children: React.ReactNode;
  /** Set false for screens that own a FlatList; content is then only width-constrained. */
  scroll?: boolean;
  footer?: React.ReactNode;
}

/**
 * Page template: safe areas, keyboard avoidance, scrollable content, shared gutters and a
 * max content width so large phones/tablets don't stretch forms edge to edge.
 */
export function Screen({ children, scroll = true, footer }: Props) {
  const insets = useSafeAreaInsets();
  const inner = <View style={[styles.inner, !scroll && { flex: 1 }]}>{children}</View>;
  return (
    <KeyboardAvoidingView
      style={styles.root}
      behavior={Platform.OS === 'ios' ? 'padding' : undefined}
    >
      {scroll ? (
        <ScrollView
          keyboardShouldPersistTaps="handled"
          contentContainerStyle={[styles.scroll, { paddingBottom: spacing.xxl + insets.bottom }]}
        >
          {inner}
        </ScrollView>
      ) : (
        <View style={styles.flat}>{inner}</View>
      )}
      {footer ? (
        <View style={[styles.footer, { paddingBottom: spacing.md + insets.bottom }]}>
          <View style={styles.inner}>{footer}</View>
        </View>
      ) : null}
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.bg },
  scroll: { flexGrow: 1, paddingHorizontal: sizes.screenGutter, paddingTop: spacing.lg, alignItems: 'center' },
  flat: { flex: 1, paddingHorizontal: sizes.screenGutter, paddingTop: spacing.lg, alignItems: 'center' },
  inner: { width: '100%', maxWidth: sizes.maxContentWidth, gap: spacing.lg, flexShrink: 1 },
  footer: {
    backgroundColor: colors.surface,
    borderTopWidth: StyleSheet.hairlineWidth,
    borderTopColor: colors.border,
    paddingTop: spacing.md,
    paddingHorizontal: sizes.screenGutter,
    alignItems: 'center',
  },
});
