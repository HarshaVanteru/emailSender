import type { ConnectedAccount } from './types';
import { apiUrl, getAuthHeaders } from '../../shared/api/client';

export function getGmailAuthUrl(renewConsent = false, mailboxAccess = false, modifyAccess = false, draftAccess = false): string {
  const params = new URLSearchParams();
  if (renewConsent) params.set('renew_consent', 'true');
  if (mailboxAccess) params.set('mailbox_access', 'true');
  if (modifyAccess) params.set('modify_access', 'true');
  if (draftAccess) params.set('draft_access', 'true');
  return apiUrl('auth/google') + (params.size ? `?${params}` : '');
}

export async function fetchConnectedAccounts(signal?: AbortSignal): Promise<ConnectedAccount[]> {
  const response = await fetch(apiUrl('accounts'), { headers: getAuthHeaders(), signal });
  if (!response.ok) throw new Error('Could not load Gmail connections. Please try again.');
  return response.json();
}

export async function disconnectAccount(accountId: number): Promise<void> {
  const response = await fetch(apiUrl(`accounts/${accountId}`), {
    method: 'DELETE', headers: getAuthHeaders(),
  });
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new Error(data.detail || 'Could not disconnect Gmail. Please try again.');
  }
}
