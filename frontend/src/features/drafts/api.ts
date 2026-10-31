import type { SendEmailPayload, SendEmailResponse } from '../compose-email/types';
import type { GmailDraftDetail, GmailDraftPage } from './types';
import { apiRequest } from '../../shared/api/client';
import { submitSend } from '../../shared/api/jobs';

export const listGmailDrafts = (id: number, token?: string | null) => apiRequest<GmailDraftPage>(`accounts/${id}/drafts${token ? `?page_token=${encodeURIComponent(token)}` : ''}`);

export const getGmailDraft = (id: number, draftId: string) => apiRequest<GmailDraftDetail>(`accounts/${id}/drafts/${encodeURIComponent(draftId)}`);

export const saveGmailDraft = (id: number, payload: SendEmailPayload & { content_hash?: string }, draftId?: string) =>
  apiRequest<GmailDraftDetail>(`accounts/${id}/drafts${draftId ? `/${encodeURIComponent(draftId)}` : ''}`, undefined, draftId ? 'PUT' : 'POST', payload);

export const sendGmailDraft = (id: number, draftId: string, contentHash: string) =>
  submitSend<SendEmailResponse>(id, `accounts/${id}/drafts/${encodeURIComponent(draftId)}/send-jobs`, { content_hash: contentHash });

export const discardGmailDraft = (id: number, draftId: string, contentHash: string) =>
  apiRequest<void>(`accounts/${id}/drafts/${encodeURIComponent(draftId)}`, undefined, 'DELETE', { content_hash: contentHash });
