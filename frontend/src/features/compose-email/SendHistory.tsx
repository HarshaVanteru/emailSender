import { useEffect, useState } from 'react';
import { apiRequest } from '../../shared/api/client';
import type { DurableJob } from '../../shared/api/jobs';

export function SendHistory({ accountId }: { accountId: number }) {
  const [jobs, setJobs] = useState<DurableJob<{ message_id: string }>[]>([]);
  const [error, setError] = useState('');
  const [revision, setRevision] = useState(0);
  const [open, setOpen] = useState(false);
  useEffect(() => {
    if (!open) return;
    const controller = new AbortController();
    void apiRequest<typeof jobs>(`accounts/${accountId}/send-jobs`, controller.signal).then(data => {
      if (!Array.isArray(data)) throw new Error('Send status is unavailable. Refresh to try again.');
      if (!controller.signal.aborted) setJobs(data);
    })
      .catch(reason => { if (!controller.signal.aborted) setError(reason.message); });
    const update = () => setRevision(value => value + 1);
    window.addEventListener('email-studio-send-updated', update);
    return () => { controller.abort(); window.removeEventListener('email-studio-send-updated', update); };
  }, [accountId, revision, open]);
  async function reconcile(id: string) {
    setError('');
    try { await apiRequest(`accounts/${accountId}/send-jobs/${id}/reconcile`, undefined, 'POST'); setRevision(value => value + 1); }
    catch (reason) { setError(reason instanceof Error ? reason.message : 'Could not check Gmail Sent.'); }
  }
  return <details className="mail-state" onToggle={event => setOpen(event.currentTarget.open)}><summary>Recent send status</summary>
    <button type="button" onClick={() => { setError(''); setRevision(value => value + 1); }}>Refresh send status</button>
    {error && <p role="alert">{error}</p>}
    {jobs.length === 0 && <p>No sends recorded for this account.</p>}
    <ul>{jobs.map(job => <li key={job.id}><span>{job.operation}: {job.status}</span>{job.error_code && <span> ({job.error_code})</span>}
      {job.status === 'unknown' && <><p>Delivery is uncertain. Check Sent before composing another send.</p><button type="button" onClick={() => void reconcile(job.id)}>Check Gmail Sent</button></>}
    </li>)}</ul>
  </details>;
}
