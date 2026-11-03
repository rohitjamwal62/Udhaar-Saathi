// Signs Expo CLI in as YOU (e.g. rohit62) without the robot EXPO_TOKEN getting in the way.
// Usage:  npm run login -- -u rohit62      (asks for your password in this terminal)
// This avoids the browser login, which crashes on Windows ("start" cuts the URL at the first &).
const { spawn } = require('child_process');
const env = { ...process.env };
// Windows: make Expo's browser login work (see scripts/winfix.js).
env.NODE_OPTIONS = `${env.NODE_OPTIONS ? env.NODE_OPTIONS + ' ' : ''}--require "${require('path').join(__dirname, 'winfix.js').split(require('path').sep).join('/')}"`;
delete env.EXPO_TOKEN;
const child = spawn('npx', ['expo', 'login', ...process.argv.slice(2)], { stdio: 'inherit', env, shell: true });
child.on('exit', (code) => process.exit(code ?? 0));
