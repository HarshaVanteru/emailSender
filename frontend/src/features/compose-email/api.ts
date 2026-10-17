import type { SendEmailPayload, SendEmailResponse, ThreadComposeMode, ThreadComposePreview, ThreadSendPayload, ThreadSendResponse } from './types';
import { apiUrl, getAuthHeaders, mailboxRequest } from '../../shared/api/client';

export const fetchThreadCompose = (accountId: number, messageId: number, mode: ThreadComposeMode) =>
  mailboxRequest<ThreadComposePreview>(`accounts/${accountId}/messages/${messageId}/compose?mode=${mode}`);

export const sendThreadMessage = (accountId: number, messageId: number, payload: ThreadSendPayload) =>
  mailboxRequest<ThreadSendResponse>(`accounts/${accountId}/messages/${messageId}/send`, undefined, 'POST', payload);

export async function sendEmail(payload: SendEmailPayload): Promise<SendEmailResponse> {
  const res = await fetch(apiUrl('gmail/send'), {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...getAuthHeaders()
    },
    body: JSON.stringify(payload),
  });

  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(data.detail || `Email dispatch failed with HTTP ${res.status}`);
  }

  return data;
}

export function readFileAsBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const result = typeof reader.result === 'string' ? reader.result : '';
      const [, base64Data = ''] = result.split(',', 2);
      resolve(base64Data);
    };
    reader.onerror = () => reject(new Error('Failed to read file for attachment.'));
    reader.readAsDataURL(file);
  });
}
