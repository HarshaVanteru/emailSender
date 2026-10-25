import type { MailLabel, MailSummary, MailDetail, MailPage, ThreadPage } from './types';
import { apiRequest } from '../../shared/api/client';

export function fetchMail(accountId: number, label: string, unread: boolean, q: string, token: string | null, signal?: AbortSignal, importance?: MailSummary['ai_importance']) {
  const params = new URLSearchParams({ account_id: String(accountId), page_size: '30' });
  if (label) params.set('label', label);
  if (importance) params.set('importance', importance);
  if (unread) params.set('unread', 'true');
  if (q) params.set('q', q);
  if (token) params.set('page_token', token);
  return apiRequest<MailPage<MailSummary>>(`${q ? 'search' : 'emails'}?${params}`, signal);
}

export function fetchThread(accountId: number, threadId: number, token: string | null, signal?: AbortSignal) {
  const params = new URLSearchParams({ account_id: String(accountId) });
  if (token) params.set('page_token', token);
  return apiRequest<ThreadPage>(`threads/${threadId}?${params}`, signal);
}

export const fetchLabels = (id: number, signal?: AbortSignal) => apiRequest<MailLabel[]>(`accounts/${id}/labels`, signal);

export type MailAction = 'read' | 'unread' | 'star' | 'unstar' | 'archive' | 'trash';

export function changeMail(accountId: number, messageId: number, action: MailAction, signal?: AbortSignal) {
  const path = `emails/${messageId}?account_id=${accountId}`;
  if (action === 'archive') return apiRequest<MailDetail>(`emails/${messageId}/archive?account_id=${accountId}`, signal, 'POST');
  if (action === 'trash') return apiRequest<MailDetail>(path, signal, 'DELETE');
  return apiRequest<MailDetail>(path, signal, 'PATCH', action === 'read' ? { read: true } : action === 'unread'
    ? { read: false } : action === 'star' ? { starred: true } : { starred: false });
}
