import type { ChatMessage, CopilotResponse, ContextAiOperation, ContextAiSuggestion } from './types';
import { apiRequest } from '../../shared/api/client';
import { waitForJob, type DurableJob } from '../../shared/api/jobs';

export const listContextAiSuggestions = (accountId: number, threadId: number) =>
  apiRequest<ContextAiSuggestion[]>(`accounts/${accountId}/threads/${threadId}/ai`);

export async function generateContextAiSuggestion(accountId: number, threadId: number, operation: ContextAiOperation,
  payload: { instruction?: string; text?: string; message_id?: number }) {
  const path = `accounts/${accountId}/threads/${threadId}/ai/jobs`;
  const job = await apiRequest<DurableJob<ContextAiSuggestion>>(`${path}/${operation}`, undefined, 'POST', payload);
  return waitForJob(job, `${path}/${job.id}`, 'ai');
}

export async function generateEmailDraft(
  instruction: string,
  history: ChatMessage[] = []
): Promise<CopilotResponse> {
  const job = await apiRequest<DurableJob<CopilotResponse>>('ai/generate-email', undefined, 'POST',
    { instruction, messages: history }, 'AI generation failed. Please try again.');
  return waitForJob(job, `ai/jobs/${job.id}`, 'ai');
}
