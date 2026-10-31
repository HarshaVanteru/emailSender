import { apiRequest } from './client';

export type DurableJob<T> = { id: string; operation: string; status: string; result: T | null; error_code: string | null };

export async function waitForJob<T>(initial: DurableJob<T>, statusPath: string, kind: 'send' | 'ai'): Promise<T> {
  let job = initial;
  const deadline = Date.now() + 5 * 60_000;
  while (job.status === 'pending' || job.status === 'processing') {
    if (Date.now() > deadline) throw new Error(`This ${kind === 'send' ? 'send' : 'suggestion'} is still queued. Check its status before trying again. Job: ${job.id}`);
    await new Promise(resolve => setTimeout(resolve, 2000));
    job = await apiRequest<DurableJob<T>>(statusPath);
  }
  if (job.status === 'unknown') throw new Error(`Gmail could not confirm delivery. Check Sent before trying again. Job: ${job.id}`);
  if (job.status !== 'sent' && job.status !== 'completed') throw new Error(`The ${kind} job failed. ${job.error_code || 'Try again after reviewing the latest content.'}`);
  if (!job.result) throw new Error('The completed job has no result. Refresh and check its status.');
  return job.result;
}

export async function submitSend<T>(accountId: number, path: string, body: object): Promise<T> {
  const key = crypto.randomUUID();
  const job = await apiRequest<DurableJob<T>>(path, undefined, 'POST', body,
    'Could not queue this send. Check send status before trying again.', { 'Idempotency-Key': key });
  window.dispatchEvent(new Event('email-studio-send-updated'));
  // Only task status is polled. A timeout never issues another send request.
  try { return await waitForJob(job, `accounts/${accountId}/send-jobs/${job.id}`, 'send'); }
  finally { window.dispatchEvent(new Event('email-studio-send-updated')); }
}
