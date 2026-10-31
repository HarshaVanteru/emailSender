import { useEffect, useState } from 'react';
import { apiRequest } from '../../shared/api/client';

type Diagnostics = {
  requires_reauth: boolean; sync_paused: boolean; watch_last_error_code: string | null;
  failed_sync_jobs: { id: number; attempts: number; error_code: string | null }[];
  send_jobs: Record<string, number>; ai_jobs: Record<string, number>;
};

export function AccountDiagnostics({ accountId }: { accountId: number }) {
  const [open, setOpen] = useState(false);
  const [data, setData] = useState<Diagnostics | null>(null);
  const [error, setError] = useState('');
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    if (!open) return;
    const controller = new AbortController();
    void apiRequest<Diagnostics>(`accounts/${accountId}/diagnostics`, controller.signal).then(result => {
      if (!controller.signal.aborted) setData(result);
    }).catch(reason => { if (!controller.signal.aborted) setError(reason.message); });
    return () => controller.abort();
  }, [open, accountId, revision]);
  async function retry() {
    setError('');
    try { await apiRequest(`accounts/${accountId}/sync`, undefined, 'POST'); setRevision(value => value + 1); }
    catch (reason) { setError(reason instanceof Error ? reason.message : 'Could not resume mailbox updates.'); }
  }
  return <details onToggle={event => setOpen(event.currentTarget.open)} className="text-xs">
    <summary>Connection diagnostics</summary>
    {error && <p role="alert">{error}</p>}
    {data && <><p>{data.requires_reauth ? 'Reconnect this Gmail account.' : data.sync_paused ? 'Mailbox updates are paused.' : 'Mailbox updates are enabled.'}</p>
      <p>Uncertain sends: {data.send_jobs.unknown || 0}. Failed AI jobs: {data.ai_jobs.failed || 0}.</p>
      {data.watch_last_error_code && <p>Push renewal failed. Scheduled mailbox updates continue.</p>}
      {data.failed_sync_jobs.length > 0 && <ul>{data.failed_sync_jobs.map(job => <li key={job.id}>Sync {job.id}: {job.error_code || 'failed'} ({job.attempts} attempts)</li>)}</ul>}
      {data.sync_paused && !data.requires_reauth && <button type="button" onClick={() => void retry()}>Resume mailbox updates</button>}
    </>}
    <button type="button" onClick={() => { setError(''); setRevision(value => value + 1); }}>Refresh diagnostics</button>
  </details>;
}
