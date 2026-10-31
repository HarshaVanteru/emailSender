import { useState } from 'react';
import { connectGmailAccount } from './api';

export function ConnectAccount({ accountId, children }: { accountId?: number; children: React.ReactNode }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  async function connect() {
    setBusy(true);
    setError('');
    try { await connectGmailAccount(accountId); }
    catch (reason) { setError(reason instanceof Error ? reason.message : 'Connection failed. Try again.'); setBusy(false); }
  }
  return <><button type="button" disabled={busy} onClick={() => void connect()}>{busy ? 'Connecting...' : children}</button>{error && <span role="alert">{error}</span>}</>;
}
