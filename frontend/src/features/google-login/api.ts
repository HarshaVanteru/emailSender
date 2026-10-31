import type { ConnectedAccount } from './types';
import { apiUrl, apiRequest } from '../../shared/api/client';

export function getGmailAuthUrl(renewConsent = false, mailboxAccess = false, modifyAccess = false, draftAccess = false): string {
  const params = new URLSearchParams();
  if (renewConsent) params.set('renew_consent', 'true');
  if (mailboxAccess) params.set('mailbox_access', 'true');
  if (modifyAccess) params.set('modify_access', 'true');
  if (draftAccess) params.set('draft_access', 'true');
  return apiUrl('auth/google') + (params.size ? `?${params}` : '');
}

export const fetchConnectedAccounts = (signal?: AbortSignal) =>
  apiRequest<ConnectedAccount[]>('accounts', signal, 'GET', undefined, 'Could not load Gmail connections. Please try again.');

export const disconnectAccount = (accountId: number) =>
  apiRequest<void>(`accounts/${accountId}`, undefined, 'DELETE', undefined, 'Could not disconnect Gmail. Please try again.');

export async function connectGmailAccount(accountId?: number) {
  const result = await apiRequest<{ authorization_url: string }>(
    accountId === undefined ? 'accounts/google/connect' : `accounts/${accountId}/reconnect`,
    undefined, 'POST');
  window.location.assign(result.authorization_url);
}
