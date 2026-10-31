import type { SendEmailPayload, SendEmailResponse, ThreadComposeMode, ThreadComposePreview, ThreadSendPayload, ThreadSendResponse } from './types';
import { apiRequest } from '../../shared/api/client';
import { submitSend } from '../../shared/api/jobs';

export const fetchThreadCompose = (accountId: number, messageId: number, mode: ThreadComposeMode) =>
  apiRequest<ThreadComposePreview>(`accounts/${accountId}/messages/${messageId}/compose?mode=${mode}`);

export const sendThreadMessage = (accountId: number, messageId: number, payload: ThreadSendPayload) =>
  submitSend<ThreadSendResponse>(accountId, `accounts/${accountId}/messages/${messageId}/send-jobs`, payload);

export const sendEmail = (payload: SendEmailPayload) => {
  if (!payload.account_id) return Promise.reject(new Error('Choose a sending account.'));
  return submitSend<SendEmailResponse>(payload.account_id, `accounts/${payload.account_id}/emails/send`, payload);
};

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
