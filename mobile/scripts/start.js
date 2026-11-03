// Starts Metro for local testing in Expo Go over your Wi-Fi (LAN).
//
// * EXPO_TOKEN is removed for this process: it makes Expo CLI act as a robot account, which then
//   clashes with the account signed in to Expo Go ("these accounts need to match").
// * It runs with --offline so Expo CLI never asks you to log in (the login prompt tries to open a
//   browser through `cmd start`, which crashes on Windows). Offline only skips Expo's cloud calls;
//   the QR code / exp://<your-ip>:8081 link still works on the same Wi-Fi.
// * It refuses to start if the port is already taken by an OLD Metro server, because Expo Go would
//   keep connecting to that old server (and its old login).
//
// Use `npm run start:online` (normal Expo CLI) or `npm run start:tunnel` when you need the cloud.
const { spawn } = require('child_process');
const net = require('net');

const fs = require('fs');
const path = require('path');

const env = { ...process.env };
// Windows: make Expo's browser login work (see scripts/winfix.js).
env.NODE_OPTIONS = `${env.NODE_OPTIONS ? env.NODE_OPTIONS + ' ' : ''}--require "${require('path').join(__dirname, 'winfix.js').split(require('path').sep).join('/')}"`;
let args = process.argv.slice(2);
const wantsAccount = args.includes('--account');

// The robot EXPO_TOKEN from your Windows environment is never used for local testing.
if (env.EXPO_TOKEN) {
  delete env.EXPO_TOKEN;
  console.log('[start] EXPO_TOKEN from your environment ignored (your system setting is unchanged).');
}
// --account: sign Expo CLI in as YOU using a personal access token kept in mobile/.env.account
// (git-ignored). Create it at expo.dev -> your account -> Access tokens (a personal token, not a robot).
if (wantsAccount) {
  const file = path.join(__dirname, '..', '.env.account');
  const m = fs.existsSync(file) ? /^\s*EXPO_TOKEN\s*=\s*(\S+)\s*$/m.exec(fs.readFileSync(file, 'utf8')) : null;
  if (m) {
    env.EXPO_TOKEN = m[1];
    console.log('[start] Using the personal Expo token from .env.account.');
  } else {
    console.log('[start] No mobile/.env.account found; using your saved `npm run login` session if there is one.');
  }
}
// --account: you are signed in to Expo CLI as yourself (npm run login). Keeps the project's Expo account
// link (owner/projectId) so Expo can sign the project for the Expo Go user that matches you.
const account = args.includes('--account');
if (account) env.UDHAAR_LOCAL_DEV = '0';
const online = account || args.includes('--online') || args.includes('--tunnel');
args = args.filter((a) => a !== '--online' && a !== '--account');
if (!online && !args.includes('--offline')) args.push('--offline');

function tryConnect(host, port) {
  return new Promise((resolve) => {
    const sock = net.connect({ host, port, timeout: 700 });
    sock.once('connect', () => { sock.destroy(); resolve(true); });
    sock.once('timeout', () => { sock.destroy(); resolve(false); });
    sock.once('error', () => resolve(false));
  });
}

// Something is listening if a connection succeeds on IPv4 or IPv6 localhost.
async function portBusy(port) {
  return (await tryConnect('127.0.0.1', port)) || (await tryConnect('::1', port));
}

async function main() {
  const i = args.indexOf('--port');
  const port = i >= 0 ? Number(args[i + 1]) : 8081;
  if (await portBusy(port)) {
    console.error('');
    console.error(`[start] Port ${port} is already in use: an OLD Metro/Expo server is still running.`);
    console.error('Expo Go would keep talking to that old server (and its old login), so the account error stays.');
    console.error('Close it first: press Ctrl+C in the terminal that runs it, or stop it with:');
    console.error(`  PowerShell:  Stop-Process -Id (Get-NetTCPConnection -LocalPort ${port} -State Listen).OwningProcess -Force`);
    console.error('Then run `npm start` again.');
    console.error('');
    process.exit(1);
  }
  const child = spawn('npx', ['expo', 'start', ...args], { stdio: 'inherit', env, shell: true });
  child.on('exit', (code) => process.exit(code ?? 0));
}

main();
