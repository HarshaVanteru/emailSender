import { buildApiUrl } from './apiUrl';
import { getToken } from '../../features/google-login/session';

const API_BASE = import.meta.env.VITE_API_BASE_URL || '';

export const apiUrl = (path: string) => buildApiUrl(API_BASE, path);

export function getAuthHeaders(): Record<string, string> {
  const token = getToken();
  return token ? { 'Authorization': `Bearer ${token}` } : {};
}

export class ApiError extends Error {
  readonly status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
  }
}

export async function apiRequest<T>(path: string, signal?: AbortSignal, method = 'GET', body?: object,
  errorMessage = 'Could not load your mail. Please try again.'): Promise<T> {
  const response = await fetch(apiUrl(path), { headers: { ...getAuthHeaders(), ...(body ? { 'Content-Type': 'application/json' } : {}) },
    signal, method, ...(body ? { body: JSON.stringify(body) } : {}) });
  const data = await response.json().catch(() => ({}));
  // A broker outage still returns the durable job ID so the UI can track recovery.
  if (response.status === 503 && data.detail?.accepted && data.detail?.job_id) {
    return { id: data.detail.job_id, status: 'queued', error_code: 'queue_unavailable' } as T;
  }
  if (!response.ok) {
    if (response.status === 401) throw new ApiError('Your session expired. Reconnect Gmail to continue.', response.status);
    throw new ApiError(typeof data.detail === 'string' ? data.detail : data.detail?.message || errorMessage, response.status);
  }
  return data;
}
