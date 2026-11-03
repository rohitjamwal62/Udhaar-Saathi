import React from 'react';
import {
  ActivityIndicator,
  Pressable,
  StyleSheet,
  Text,
  View,
  type PressableProps,
  type StyleProp,
  type TextProps,
  type ViewStyle,
} from 'react-native';
import { colors, elevation, radius, sizes, spacing, typography } from '../../core/theme';

// ── Text ────────────────────────────────────────────────────────────────
type Variant = keyof typeof typography;
interface AppTextProps extends TextProps {
  variant?: Variant;
  color?: string;
  center?: boolean;
}
/** Text never sets a max font multiplier: it wraps/grows with the system font scale. */
export function AppText({ variant = 'body', color = colors.text, center, style, ...rest }: AppTextProps) {
  return <Text {...rest} style={[typography[variant], { color }, center && { textAlign: 'center' }, style]} />;
}

// ── Button ──────────────────────────────────────────────────────────────
interface ButtonProps extends Omit<PressableProps, 'style' | 'children'> {
  title: string;
  variant?: 'primary' | 'secondary' | 'danger' | 'ghost';
  loading?: boolean;
  style?: StyleProp<ViewStyle>;
}
export function Button({ title, variant = 'primary', loading, disabled, style, ...rest }: ButtonProps) {
  const off = disabled || loading;
  const bg = { primary: colors.primary, secondary: colors.surface, danger: colors.danger, ghost: 'transparent' }[variant];
  const fg = variant === 'primary' || variant === 'danger' ? '#fff' : colors.primary;
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={title}
      accessibilityState={{ disabled: !!off, busy: !!loading }}
      disabled={off}
      {...rest}
      style={({ pressed }) => [
        styles.button,
        { backgroundColor: bg, opacity: off ? 0.5 : pressed ? 0.85 : 1 },
        variant === 'secondary' && { borderWidth: 1.5, borderColor: colors.primary },
        style,
      ]}
    >
      {loading ? <ActivityIndicator color={fg} /> : <AppText variant="bodyStrong" color={fg} center>{title}</AppText>}
    </Pressable>
  );
}

// ── Card ────────────────────────────────────────────────────────────────
export function Card({ children, style }: { children: React.ReactNode; style?: StyleProp<ViewStyle> }) {
  return <View style={[styles.card, style]}>{children}</View>;
}

// ── Chip (single-select option) ─────────────────────────────────────────
export function Chip({ label, selected, onPress }: { label: string; selected?: boolean; onPress?: () => void }) {
  return (
    <Pressable
      onPress={onPress}
      accessibilityRole="button"
      accessibilityState={{ selected: !!selected }}
      style={[styles.chip, selected && { backgroundColor: colors.primary, borderColor: colors.primary }]}
    >
      <AppText variant="label" color={selected ? '#fff' : colors.text}>{label}</AppText>
    </Pressable>
  );
}

export function ChipRow({ children }: { children: React.ReactNode }) {
  return <View style={styles.chipRow}>{children}</View>;
}

// ── Badge ───────────────────────────────────────────────────────────────
type Tone = 'neutral' | 'success' | 'warning' | 'danger' | 'info';
const TONES: Record<Tone, { bg: string; fg: string }> = {
  neutral: { bg: colors.border, fg: colors.textMuted },
  success: { bg: colors.successSoft, fg: colors.success },
  warning: { bg: colors.warningSoft, fg: colors.warning },
  danger: { bg: colors.dangerSoft, fg: colors.danger },
  info: { bg: colors.infoSoft, fg: colors.info },
};
export function Badge({ label, tone = 'neutral' }: { label: string; tone?: Tone }) {
  const t = TONES[tone];
  return (
    <View style={[styles.badge, { backgroundColor: t.bg }]}>
      <AppText variant="caption" color={t.fg} style={{ fontWeight: '600' }}>{label}</AppText>
    </View>
  );
}

// ── Banner ──────────────────────────────────────────────────────────────
export function Banner({ tone = 'info', children }: { tone?: Tone; children: React.ReactNode }) {
  const t = TONES[tone];
  return (
    <View style={[styles.banner, { backgroundColor: t.bg }]} accessibilityRole="alert">
      <AppText variant="body" color={t.fg}>{children}</AppText>
    </View>
  );
}

// ── Empty / loading / error states ──────────────────────────────────────
export function EmptyState({ title, body, action }: { title: string; body?: string; action?: React.ReactNode }) {
  return (
    <View style={styles.empty}>
      <AppText variant="heading" center>{title}</AppText>
      {body ? <AppText color={colors.textMuted} center>{body}</AppText> : null}
      {action}
    </View>
  );
}

export function Loading() {
  return (
    <View style={styles.empty} accessibilityLabel="Loading">
      <ActivityIndicator size="large" color={colors.primary} />
    </View>
  );
}

export function ErrorState({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <View style={styles.empty}>
      <AppText variant="heading" center color={colors.danger}>Something went wrong</AppText>
      <AppText center color={colors.textMuted}>{message}</AppText>
      {onRetry ? <Button title="Try again" variant="secondary" onPress={onRetry} /> : null}
    </View>
  );
}

// ── Layout helpers ──────────────────────────────────────────────────────
export function SectionHeader({ title, right }: { title: string; right?: React.ReactNode }) {
  return (
    <View style={styles.sectionHeader}>
      <AppText variant="heading" style={{ flexShrink: 1 }}>{title}</AppText>
      {right}
    </View>
  );
}

export function Row({
  left, right, onPress, style,
}: { left: React.ReactNode; right?: React.ReactNode; onPress?: () => void; style?: StyleProp<ViewStyle> }) {
  const body = (
    <View style={[styles.row, style]}>
      <View style={{ flex: 1, flexShrink: 1 }}>{left}</View>
      {right ? <View style={{ alignItems: 'flex-end', flexShrink: 0 }}>{right}</View> : null}
    </View>
  );
  if (!onPress) return body;
  return (
    <Pressable onPress={onPress} accessibilityRole="button" style={({ pressed }) => ({ opacity: pressed ? 0.7 : 1 })}>
      {body}
    </Pressable>
  );
}

export const Divider = () => <View style={{ height: StyleSheet.hairlineWidth, backgroundColor: colors.border }} />;
export const Spacer = ({ size = spacing.lg }: { size?: number }) => <View style={{ height: size }} />;

export function KeyValue({ label, value, strong }: { label: string; value: string; strong?: boolean }) {
  return (
    <View style={styles.kv}>
      <AppText color={colors.textMuted} style={{ flexShrink: 1 }}>{label}</AppText>
      <AppText variant={strong ? 'bodyStrong' : 'body'} style={{ flexShrink: 1, textAlign: 'right' }}>{value}</AppText>
    </View>
  );
}

const styles = StyleSheet.create({
  button: {
    minHeight: sizes.buttonHeight,
    borderRadius: radius.md,
    paddingHorizontal: spacing.xl,
    paddingVertical: spacing.sm,
    alignItems: 'center',
    justifyContent: 'center',
  },
  card: {
    backgroundColor: colors.surface,
    borderRadius: radius.lg,
    padding: sizes.cardPadding,
    gap: spacing.sm,
    ...elevation.card,
  },
  chip: {
    minHeight: sizes.minTouch,
    paddingHorizontal: spacing.lg,
    borderRadius: radius.pill,
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: colors.surface,
    alignItems: 'center',
    justifyContent: 'center',
  },
  chipRow: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.sm },
  badge: { paddingHorizontal: spacing.sm, paddingVertical: 2, borderRadius: radius.pill, alignSelf: 'flex-start' },
  banner: { padding: spacing.md, borderRadius: radius.md },
  empty: { padding: spacing.xxl, gap: spacing.md, alignItems: 'center', justifyContent: 'center' },
  sectionHeader: {
    flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center',
    gap: spacing.sm, marginTop: spacing.sm,
  },
  row: {
    flexDirection: 'row', alignItems: 'center', gap: spacing.md,
    minHeight: sizes.minTouch, paddingVertical: spacing.sm,
  },
  kv: { flexDirection: 'row', justifyContent: 'space-between', gap: spacing.md },
});
