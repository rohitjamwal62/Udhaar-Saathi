// Central design tokens. Every screen/component takes sizes from here so the
// UI stays visually consistent while layouts adapt to the window width.
export const colors = {
  primary: '#0B6E4F',
  primaryDark: '#084C37',
  primarySoft: '#E3F3EC',
  accent: '#F2A900',
  bg: '#F6F7F5',
  surface: '#FFFFFF',
  text: '#17211C',
  textMuted: '#5B6761',
  border: '#DDE3DF',
  danger: '#B3261E',
  dangerSoft: '#FCE8E6',
  warning: '#8A5A00',
  warningSoft: '#FFF2D6',
  success: '#0B6E4F',
  successSoft: '#E3F3EC',
  info: '#1F5FA8',
  infoSoft: '#E4EEF9',
} as const;

export const spacing = { xs: 4, sm: 8, md: 12, lg: 16, xl: 24, xxl: 32 } as const;
export const radius = { sm: 8, md: 12, lg: 16, pill: 999 } as const;

export const sizes = {
  buttonHeight: 52,
  inputHeight: 52,
  minTouch: 48,
  icon: 24,
  cardPadding: 16,
  screenGutter: 16,
  maxContentWidth: 720,
} as const;

export const typography = {
  display: { fontSize: 28, fontWeight: '700' as const, lineHeight: 34 },
  title: { fontSize: 22, fontWeight: '700' as const, lineHeight: 28 },
  heading: { fontSize: 18, fontWeight: '600' as const, lineHeight: 24 },
  body: { fontSize: 16, fontWeight: '400' as const, lineHeight: 22 },
  bodyStrong: { fontSize: 16, fontWeight: '600' as const, lineHeight: 22 },
  caption: { fontSize: 13, fontWeight: '400' as const, lineHeight: 18 },
  label: { fontSize: 14, fontWeight: '600' as const, lineHeight: 20 },
} as const;

export const elevation = {
  card: {
    shadowColor: '#000',
    shadowOpacity: 0.06,
    shadowRadius: 6,
    shadowOffset: { width: 0, height: 2 },
    elevation: 2,
  },
} as const;

export const breakpoints = { regular: 600 } as const;
