import { useEffect, useEffectEvent, useState } from 'react';
import { apiRequest, ApiError } from '../../shared/api/client';

type HistoryState = { session_id: string; status: string; has_more: boolean; error_code: string | null };

export function HistoryControl({ accountId, label, onLoaded }: { accountId: number; label: string; onLoaded: () => void }) {
  const [session, setSession] = useState<HistoryState | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  async function load() {
    setBusy(true); setError('');
    try {
      const row = await apiRequest<HistoryState>(`accounts/${accountId}/sync/historical`, undefined, 'POST',
        session ? { session_id: session.session_id } : { label: label || undefined });
      setSession(row);
    } catch (reason) {
      if (reason instanceof ApiError && reason.status === 410) setSession(null);
      setError(reason instanceof Error ? reason.message : 'Could not load older mail.');
    }
    finally { setBusy(false); }
  }
  const sessionId = session?.session_id;
  const pending = session?.status === 'pending';
  const loaded = useEffectEvent(onLoaded);
  useEffect(() => {
    if (!pending || !sessionId) return;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const row = await apiRequest<HistoryState>(`accounts/${accountId}/sync/sessions/${sessionId}`, controller.signal);
        if (controller.signal.aborted) return;
        setSession(row);
        if (row.status === 'pending') timer = setTimeout(() => void poll(), 3000);
        else if (row.status === 'failed' || row.status === 'expired') {
          if (row.status === 'expired') setSession(null);
          setError('Older mail could not be loaded. Try again.');
        }
        else loaded();
      } catch (reason) { if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : 'Could not check older mail.'); }
    };
    timer = setTimeout(() => void poll(), 2000);
    return () => { controller.abort(); clearTimeout(timer); };
  }, [accountId, pending, sessionId]);
  return <div className="mail-state">
    {error && <p role="alert">{error}</p>}
    {session?.status === 'completed' ? <p>All older mail in this view has been loaded.</p>
      : <button className="mail-button" disabled={busy || pending} onClick={() => void load()}>{busy || pending ? 'Loading older mail...' : 'Load older mail from Gmail'}</button>}
  </div>;
}
