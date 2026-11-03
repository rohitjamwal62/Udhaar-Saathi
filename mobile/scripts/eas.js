// Runs eas-cli with a clearly chosen identity, never "whatever EXPO_TOKEN happens to be in Windows".
//
//   npm run eas:me -- build --profile preview --platform android
//       Acts as YOU (the account you signed in with via `npm run login`, e.g. rohit62).
//       Any EXPO_TOKEN in your environment or files is ignored.
//   npm run eas -- <command>
//       Uses the token from mobile/.env.eas (git-ignored), e.g. a robot token of the owning team.
//
// Why: the project belongs to the team `rohit62s-team`. A token of any other Expo account (for example a
// leftover EXPO_TOKEN in Windows) fails with "Entity not authorized", including when generating a keystore.
const { spawn } = require('child_process');
const fs = require('fs');
const path = require('path');

const env = { ...process.env };
let args = process.argv.slice(2);
const asMe = args.includes('--me');
args = args.filter((a) => a !== '--me');

// Windows: make eas-cli's / Expo's browser login work (see scripts/winfix.js).
const fix = path.join(__dirname, 'winfix.js').split(path.sep).join('/');
env.NODE_OPTIONS = `${env.NODE_OPTIONS ? env.NODE_OPTIONS + ' ' : ''}--require "${fix}"`;

// Upload by files (limited by .easignore) instead of by git state, so uncommitted changes or a missing repo
// never block a build and secret files (.env*) are never uploaded.
env.EAS_NO_VCS = '1';

delete env.EXPO_TOKEN;
if (asMe) {
  console.log('[eas] Using your own login (npm run login). Any EXPO_TOKEN is ignored.');
} else {
  const file = path.join(__dirname, '..', '.env.eas');
  const m = fs.existsSync(file) ? /^\s*EXPO_TOKEN\s*=\s*(\S+)\s*$/m.exec(fs.readFileSync(file, 'utf8')) : null;
  if (m) {
    env.EXPO_TOKEN = m[1];
    console.log('[eas] Using the token from mobile/.env.eas.');
  } else {
    console.warn('[eas] No token in mobile/.env.eas, so no token is used. Run `npm run login`, then `npm run eas:me -- ...`.');
  }
}

const child = spawn('npx', ['eas-cli', ...args], { stdio: 'inherit', env, shell: true });
child.on('exit', (code) => process.exit(code ?? 0));
