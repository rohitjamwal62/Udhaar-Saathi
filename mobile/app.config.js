// Dynamic config layered on top of app.json.
//
// 1) Local testing in Expo Go: keep the Expo account link (owner / EAS projectId / updates URL) ONLY when the
//    CLI is signed in as the matching account. See scripts/start.js (--account). Without a matching login the
//    link is removed for `expo start`, otherwise Expo Go (signed in as you) refuses to open the project.
//    Cloud commands (eas build / update / submit) always keep it.
//    Force either way with UDHAAR_LOCAL_DEV=1 (strip) or UDHAAR_LOCAL_DEV=0 (keep).
//
// 2) Test builds that talk to a plain http:// backend on your Wi-Fi need cleartext traffic on Android 9+.
//    That is switched on ONLY when UDHAAR_ALLOW_CLEARTEXT=1 (set in eas.json for the "preview" profile),
//    never for production builds. Production must use HTTPS.
const isLocalStart = () => {
  if (process.env.UDHAAR_LOCAL_DEV === '1') return true;
  if (process.env.UDHAAR_LOCAL_DEV === '0') return false;
  const args = process.argv.slice(2);
  return args.includes('start') && !args.includes('eas');
};

module.exports = ({ config }) => {
  let out = config;

  if (isLocalStart()) {
    const { owner, updates, runtimeVersion, extra, ...rest } = out;
    const { eas, ...otherExtra } = extra ?? {};
    out = { ...rest, extra: otherExtra };
  }

  if (process.env.UDHAAR_ALLOW_CLEARTEXT === '1') {
    out = {
      ...out,
      plugins: [
        ...(out.plugins ?? []),
        ['expo-build-properties', { android: { usesCleartextTraffic: true } }],
      ],
    };
  }

  return out;
};
