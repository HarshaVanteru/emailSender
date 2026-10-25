import type { ChatMessage, CopilotResponse, ContextAiOperation, ContextAiSuggestion } from './types';
import { apiRequest } from '../../shared/api/client';

export const listContextAiSuggestions = (accountId: number, threadId: number) =>
  apiRequest<ContextAiSuggestion[]>(`accounts/${accountId}/threads/${threadId}/ai`);

export const generateContextAiSuggestion = (accountId: number, threadId: number, operation: ContextAiOperation,
  payload: { instruction?: string; text?: string; message_id?: number }) =>
  apiRequest<ContextAiSuggestion>(`accounts/${accountId}/threads/${threadId}/ai/${operation}`, undefined, 'POST', payload);

export function generateEmailDraft(
  instruction: string,
  history: ChatMessage[] = []
): Promise<CopilotResponse> {
  return apiRequest<CopilotResponse>('ai/generate-email', undefined, 'POST',
    { instruction, messages: history }, 'AI generation failed. Please try again.');
}
