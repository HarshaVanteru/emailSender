import type { ChatMessage, CopilotResponse, ContextAiOperation, ContextAiSuggestion } from './types';
import { apiUrl, getAuthHeaders, mailboxRequest } from '../../shared/api/client';

export const listContextAiSuggestions = (accountId: number, threadId: number) =>
  mailboxRequest<ContextAiSuggestion[]>(`accounts/${accountId}/threads/${threadId}/ai`);

export const generateContextAiSuggestion = (accountId: number, threadId: number, operation: ContextAiOperation,
  payload: { instruction?: string; text?: string; message_id?: number }) =>
  mailboxRequest<ContextAiSuggestion>(`accounts/${accountId}/threads/${threadId}/ai/${operation}`, undefined, 'POST', payload);

export async function generateEmailDraft(
  instruction: string,
  history: ChatMessage[] = []
): Promise<CopilotResponse> {
  const res = await fetch(apiUrl('ai/generate-email'), {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...getAuthHeaders()
    },
    body: JSON.stringify({
      instruction,
      messages: history,
    }),
  });

  if (!res.ok) {
    const errData = await res.json().catch(() => ({}));
    throw new Error(errData.detail || `AI generation failed with HTTP ${res.status}`);
  }

  return await res.json();
}
