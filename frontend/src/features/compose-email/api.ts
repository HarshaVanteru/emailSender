import type { SendEmailPayload, SendEmailResponse, ThreadComposeMode, ThreadComposePreview, ThreadSendPayload, ThreadSendResponse } from './types';
import { apiRequest } from '../../shared/api/client';

export const fetchThreadCompose = (accountId: number, messageId: number, mode: ThreadComposeMode) =>
  apiRequest<ThreadComposePreview>(`accounts/${accountId}/messages/${messageId}/compose?mode=${mode}`);

export const sendThreadMessage = (accountId: number, messageId: number, payload: ThreadSendPayload) =>
  apiRequest<ThreadSendResponse>(`accounts/${accountId}/messages/${messageId}/send`, undefined, 'POST', payload);

export const sendEmail = (payload: SendEmailPayload) =>
  apiRequest<SendEmailResponse>('gmail/send', undefined, 'POST', payload, 'Email dispatch failed. Check Gmail Sent before trying again.');

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
