import type { GeneratedEmail, EmailAttachment } from '../compose-email/types';

export interface GmailDraftSummary { id: string; to: string; subject: string; snippet: string }

export interface GmailDraftDetail extends GeneratedEmail {
  id: string;
  cc: string;
  bcc: string;
  attachments: (Omit<EmailAttachment, 'data'> & { data: string | null; size_bytes: number })[];
  can_edit: boolean;
  content_hash: string;
}

export interface GmailDraftPage { items: GmailDraftSummary[]; next_page_token: string | null }
