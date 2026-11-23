/** What happened when the app tried to renew its login.
 *  ok = new tokens saved.
 *  rejected = the server really refused the refresh token: the user must log in again.
 *  unreachable = no network, a sleeping server, a timeout or a server error: the session is still good, so the user must NOT
 *  be signed out and the offline data must stay. The request just fails and the sync outbox retries it later. */
export type RefreshResult = 'ok' | 'rejected' | 'unreachable';

/** Only an explicit "this token is not valid" answer ends the session. */
export function refreshOutcome(status: number): RefreshResult {
  return status === 400 || status === 401 || status === 403 ? 'rejected' : 'unreachable';
}
