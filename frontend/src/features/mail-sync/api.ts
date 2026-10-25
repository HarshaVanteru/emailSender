import type { SyncJob } from './types';
import { apiRequest } from '../../shared/api/client';

export const startSync = (id: number, signal?: AbortSignal) => apiRequest<SyncJob>(`accounts/${id}/sync`, signal, 'POST');

export const fetchSyncJob = (id: number, jobId: number, signal?: AbortSignal) => apiRequest<SyncJob>(`accounts/${id}/sync-jobs/${jobId}`, signal);

export const fetchRecentSyncJobs = (id: number, signal?: AbortSignal) => apiRequest<SyncJob[]>(`accounts/${id}/sync-jobs`, signal);
