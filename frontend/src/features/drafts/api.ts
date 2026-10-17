import type { SendEmailPayload, SendEmailResponse } from '../compose-email/types';
import type { GmailDraftDetail, GmailDraftPage } from './types';
import { mailboxRequest } from '../../shared/api/client';

export const listGmailDrafts = (id: number, token?: string | null) => mailboxRequest<GmailDraftPage>(`accounts/${id}/drafts${token ? `?page_token=${encodeURIComponent(token)}` : ''}`);

export const getGmailDraft = (id: number, draftId: string) => mailboxRequest<GmailDraftDetail>(`accounts/${id}/drafts/${encodeURIComponent(draftId)}`);

export const saveGmailDraft = (id: number, payload: SendEmailPayload & { content_hash?: string }, draftId?: string) =>
  mailboxRequest<GmailDraftDetail>(`accounts/${id}/drafts${draftId ? `/${encodeURIComponent(draftId)}` : ''}`, undefined, draftId ? 'PUT' : 'POST', payload);

export const sendGmailDraft = (id: number, draftId: string, contentHash: string) =>
  mailboxRequest<SendEmailResponse>(`accounts/${id}/drafts/${encodeURIComponent(draftId)}/send`, undefined, 'POST', { content_hash: contentHash });

export const discardGmailDraft = (id: number, draftId: string, contentHash: string) =>
  mailboxRequest<void>(`accounts/${id}/drafts/${encodeURIComponent(draftId)}`, undefined, 'DELETE', { content_hash: contentHash });
