import React from 'react';
import { StyleSheet, TextInput, View, type TextInputProps } from 'react-native';
import { colors, radius, sizes, spacing } from '../../core/theme';
import { AppText } from './ui';

interface Props extends TextInputProps {
  label: string;
  error?: string | null;
  helper?: string;
  prefix?: string;
}

export function TextField({ label, error, helper, prefix, multiline, style, ...rest }: Props) {
  return (
    <View style={{ gap: spacing.xs }}>
      <AppText variant="label">{label}</AppText>
      <View style={[styles.box, error ? { borderColor: colors.danger } : null, multiline && { alignItems: 'flex-start' }]}>
        {prefix ? <AppText color={colors.textMuted} style={{ marginRight: spacing.xs }}>{prefix}</AppText> : null}
        <TextInput
          accessibilityLabel={label}
          placeholderTextColor={colors.textMuted}
          multiline={multiline}
          {...rest}
          style={[styles.input, multiline && { minHeight: 88, textAlignVertical: 'top' }, style]}
        />
      </View>
      {error ? <AppText variant="caption" color={colors.danger}>{error}</AppText> : null}
      {!error && helper ? <AppText variant="caption" color={colors.textMuted}>{helper}</AppText> : null}
    </View>
  );
}

const styles = StyleSheet.create({
  box: {
    minHeight: sizes.inputHeight,
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: colors.surface,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.md,
    paddingHorizontal: spacing.md,
  },
  input: { flex: 1, fontSize: 16, color: colors.text, paddingVertical: spacing.sm },
});
