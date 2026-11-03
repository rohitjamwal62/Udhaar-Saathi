// Preloaded with NODE_OPTIONS=--require by scripts/start.js and scripts/login.js (Windows only).
//
// Bug: Expo CLI opens your browser with `cmd /c start "" <url>`. In cmd, an unescaped `&` ends the
// command, so the login link is cut at the first `&` ("'redirect_uri' is not recognized...", exit 1) and
// Expo crashes with "cmd.exe /c start ... exited with non-zero code: 1".
// Fix: escape `&` as `^&` for http(s) links passed to `cmd /c start`. Nothing else is changed.
const cp = require('child_process');

if (process.platform === 'win32' && !cp.__udhaarWinFix) {
  const original = cp.spawn;
  cp.spawn = function patchedSpawn(command, args, options) {
    try {
      const isCmd = /(^|[\\/])cmd(\.exe)?$/i.test(String(command));
      if (isCmd && Array.isArray(args) && args[0] === '/c' && args[1] === 'start') {
        args = args.map((a, i) =>
          i >= 2 && typeof a === 'string' && /^https?:\/\//i.test(a) ? a.replace(/\^?&/g, '^&') : a);
      }
    } catch {
      /* never break process spawning because of this helper */
    }
    return original.call(this, command, args, options);
  };
  cp.__udhaarWinFix = true;
}
