import type { SyncJob } from './types';
import { mailboxRequest } from '../../shared/api/client';

export const startSync = (id: number, signal?: AbortSignal) => mailboxRequest<SyncJob>(`accounts/${id}/sync`, signal, 'POST');

export const fetchSyncJob = (id: number, jobId: number, signal?: AbortSignal) => mailboxRequest<SyncJob>(`accounts/${id}/sync-jobs/${jobId}`, signal);

export const fetchRecentSyncJobs = (id: number, signal?: AbortSignal) => mailboxRequest<SyncJob[]>(`accounts/${id}/sync-jobs`, signal);
