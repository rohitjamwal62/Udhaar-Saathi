import React, { useEffect, useState } from 'react';
import { View } from 'react-native';
import type { NativeStackScreenProps } from '@react-navigation/native-stack';
import type { RootStackParamList } from '../../app/types';
import { Screen } from '../../shared/components/Screen';
import { TextField } from '../../shared/components/TextField';
import { AppText, Banner, Button, Chip } from '../../shared/components/ui';
import { colors, spacing } from '../../core/theme';
import { useAuth } from '../../core/auth/AuthContext';
import { authApi } from '../../core/api/endpoints';
import { ApiError } from '../../core/api/client';
import { config } from '../../core/config';
import { useAction } from '../../shared/hooks';
import { normalizeMobile, passwordProblem, TERMS_VERSION } from './validation';

type P<K extends keyof RootStackParamList> = NativeStackScreenProps<RootStackParamList, K>;

function Header({ title, subtitle }: { title: string; subtitle?: string }) {
  return (
    <View style={{ gap: spacing.xs }}>
      <AppText variant="display" color={colors.primary}>{title}</AppText>
      {subtitle ? <AppText color={colors.textMuted}>{subtitle}</AppText> : null}
    </View>
  );
}

const friendly = (e: unknown, fallback: string) =>
  e instanceof ApiError ? (e.status === 400 || e.status === 401 ? fallback : e.message) : 'Something went wrong';

// ───────────────────────── Login ─────────────────────────
export function LoginScreen({ navigation, route }: P<'Login'>) {
  const { login, signInDemo } = useAuth();
  const [mobile, setMobile] = useState('');
  const [password, setPassword] = useState('');
  const [mobileErr, setMobileErr] = useState<string | null>(null);

  const submit = useAction(async () => {
    const m = normalizeMobile(mobile);
    if (!m) { setMobileErr('Enter a valid 10-digit mobile number'); return; }
    setMobileErr(null);
    if (!password) throw new Error('Enter your password');
    try {
      await login(m, password);
    } catch (e) {
      // Generic message so the screen never reveals which accounts exist.
      throw new Error(friendly(e, 'Mobile number or password is incorrect'));
    }
  });

  return (
    <Screen>
      <Header title="UdhaarSaathi" subtitle="Digital khata for your shop" />
      {route.params?.notice ? <Banner tone="success">{route.params.notice}</Banner> : null}
      <TextField label="Mobile number" prefix="+91" keyboardType="phone-pad" autoComplete="tel" value={mobile}
        onChangeText={setMobile} error={mobileErr} maxLength={13} />
      <TextField label="Password" secureTextEntry autoComplete="password" value={password} onChangeText={setPassword} />
      {submit.error ? <Banner tone="danger">{submit.error}</Banner> : null}
      {submit.busy ? <AppText variant="caption" color={colors.textMuted}>Connecting to the server. The first request after a quiet period can take up to a minute.</AppText> : null}
      <Button title="Log in" loading={submit.busy} onPress={() => submit.run()} />
      <Button title="Forgot password?" variant="ghost" onPress={() => navigation.navigate('Forgot')} />
      <Button title="Create a free account" variant="secondary" onPress={() => navigation.navigate('Signup')} />
      {config.demoMode ? (
        <Button title="Continue in demo mode (dev only)" variant="ghost" onPress={() => void signInDemo()} />
      ) : null}
    </Screen>
  );
}

// ───────────────────────── Signup ─────────────────────────
export function SignupScreen({ navigation }: P<'Signup'>) {
  const [name, setName] = useState('');
  const [mobile, setMobile] = useState('');
  const [password, setPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [language, setLanguage] = useState<'en' | 'hi'>('en');
  const [accepted, setAccepted] = useState(false);
  const [errs, setErrs] = useState<Record<string, string>>({});

  const submit = useAction(async () => {
    const e: Record<string, string> = {};
    const m = normalizeMobile(mobile);
    if (!name.trim()) e.name = 'Enter your name';
    if (!m) e.mobile = 'Enter a valid 10-digit mobile number';
    const pwErr = passwordProblem(password);
    if (pwErr) e.password = pwErr;
    if (password !== confirm) e.confirm = 'Passwords do not match';
    if (!accepted) e.terms = 'Please accept the Terms and Privacy Notice';
    setErrs(e);
    if (Object.keys(e).length || !m) return;
    try {
      const res = await authApi.signup({
        mobile: m, name: name.trim(), password, role: 'shopkeeper', language,
        accepted_terms_version: TERMS_VERSION,
      });
      navigation.navigate('Otp', { mobile: m, challengeId: res.challenge_id });
    } catch (err) {
      throw new Error(friendly(err, 'Could not create the account. Check your details and try again.'));
    }
  });

  return (
    <Screen>
      <Header title="Create account" subtitle="Registration is free. Your first 3 months are free too." />
      <TextField label="Your name" value={name} onChangeText={setName} error={errs.name} autoComplete="name" />
      <TextField label="Mobile number" prefix="+91" keyboardType="phone-pad" value={mobile} onChangeText={setMobile}
        error={errs.mobile} maxLength={13} helper="We will send an OTP to verify this number." />
      <TextField label="Password" secureTextEntry value={password} onChangeText={setPassword} error={errs.password}
        helper="At least 8 characters with letters and numbers." />
      <TextField label="Confirm password" secureTextEntry value={confirm} onChangeText={setConfirm} error={errs.confirm} />
      <View style={{ gap: spacing.sm }}>
        <AppText variant="label">Preferred language</AppText>
        <View style={{ flexDirection: 'row', gap: spacing.sm }}>
          <Chip label="English" selected={language === 'en'} onPress={() => setLanguage('en')} />
          <Chip label="हिन्दी" selected={language === 'hi'} onPress={() => setLanguage('hi')} />
        </View>
      </View>
      <View style={{ gap: spacing.xs }}>
        <Chip label={accepted ? '✓ I accept the Terms and Privacy Notice' : 'I accept the Terms and Privacy Notice'}
          selected={accepted} onPress={() => setAccepted((v) => !v)} />
        {errs.terms ? <AppText variant="caption" color={colors.danger}>{errs.terms}</AppText> : null}
      </View>
      {submit.error ? <Banner tone="danger">{submit.error}</Banner> : null}
      {submit.busy ? <AppText variant="caption" color={colors.textMuted}>Connecting to the server. The first request after a quiet period can take up to a minute.</AppText> : null}
      <Button title="Send OTP" loading={submit.busy} onPress={() => submit.run()} />
    </Screen>
  );
}

// ───────────────────────── OTP ─────────────────────────
const RESEND_SECONDS = 30;

export function OtpScreen({ route }: P<'Otp'>) {
  const { mobile } = route.params;
  const { signIn } = useAuth();
  const [challengeId, setChallengeId] = useState(route.params.challengeId);
  const [otp, setOtp] = useState('');
  const [cooldown, setCooldown] = useState(RESEND_SECONDS);

  useEffect(() => {
    if (cooldown <= 0) return;
    const t = setTimeout(() => setCooldown((c) => c - 1), 1000);
    return () => clearTimeout(t);
  }, [cooldown]);

  const verify = useAction(async () => {
    if (!/^\d{6}$/.test(otp)) throw new Error('Enter the 6-digit OTP');
    try {
      await signIn(await authApi.verifyOtp({ mobile, challenge_id: challengeId, otp }));
    } catch (e) {
      throw new Error(friendly(e, 'That OTP is incorrect or has expired'));
    }
  });
  const resend = useAction(async () => {
    const r = await authApi.requestOtp({ mobile, purpose: 'signup' });
    setChallengeId(r.challenge_id);
    setCooldown(RESEND_SECONDS);
  });

  return (
    <Screen>
      <Header title="Verify your number" subtitle={`Enter the 6-digit OTP sent to ${mobile}`} />
      <TextField label="OTP" keyboardType="number-pad" maxLength={6} value={otp} onChangeText={setOtp}
        autoComplete="sms-otp" textContentType="oneTimeCode" />
      {verify.error || resend.error ? <Banner tone="danger">{verify.error ?? resend.error}</Banner> : null}
      <Button title="Verify and continue" loading={verify.busy} onPress={() => verify.run()} />
      <Button title={cooldown > 0 ? `Resend OTP in ${cooldown}s` : 'Resend OTP'} variant="ghost"
        disabled={cooldown > 0} loading={resend.busy} onPress={() => resend.run()} />
    </Screen>
  );
}

// ───────────────────────── Forgot / reset ─────────────────────────
export function ForgotScreen({ navigation }: P<'Forgot'>) {
  const [mobile, setMobile] = useState('');
  const submit = useAction(async () => {
    const m = normalizeMobile(mobile);
    if (!m) throw new Error('Enter a valid 10-digit mobile number');
    try {
      const r = await authApi.forgotPassword({ mobile: m });
      navigation.navigate('ResetPassword', { mobile: m, challengeId: r.challenge_id });
    } catch (e) {
      throw new Error(friendly(e, 'Could not start password reset'));
    }
  });
  return (
    <Screen>
      <Header title="Reset password" subtitle="We will send an OTP to your registered mobile number." />
      <TextField label="Mobile number" prefix="+91" keyboardType="phone-pad" value={mobile} onChangeText={setMobile} maxLength={13} />
      {submit.error ? <Banner tone="danger">{submit.error}</Banner> : null}
      <Button title="Send OTP" loading={submit.busy} onPress={() => submit.run()} />
    </Screen>
  );
}

export function ResetPasswordScreen({ route, navigation }: P<'ResetPassword'>) {
  const { mobile, challengeId } = route.params;
  const [otp, setOtp] = useState('');
  const [pw, setPw] = useState('');
  const [confirm, setConfirm] = useState('');
  const submit = useAction(async () => {
    if (!/^\d{6}$/.test(otp)) throw new Error('Enter the 6-digit OTP');
    const pe = passwordProblem(pw);
    if (pe) throw new Error(pe);
    if (pw !== confirm) throw new Error('Passwords do not match');
    try {
      await authApi.resetPassword({ mobile, challenge_id: challengeId, otp, new_password: pw });
    } catch (e) {
      throw new Error(friendly(e, 'That OTP is incorrect or has expired'));
    }
    navigation.reset({ index: 0, routes: [{ name: 'Login', params: { notice: 'Password changed. Please log in.' } }] });
  });
  return (
    <Screen>
      <Header title="Choose a new password" subtitle={`OTP sent to ${mobile}`} />
      <TextField label="OTP" keyboardType="number-pad" maxLength={6} value={otp} onChangeText={setOtp} />
      <TextField label="New password" secureTextEntry value={pw} onChangeText={setPw} />
      <TextField label="Confirm new password" secureTextEntry value={confirm} onChangeText={setConfirm} />
      {submit.error ? <Banner tone="danger">{submit.error}</Banner> : null}
      <Button title="Change password" loading={submit.busy} onPress={() => submit.run()} />
    </Screen>
  );
}
