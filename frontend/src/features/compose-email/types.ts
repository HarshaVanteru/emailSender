export interface GeneratedEmail {
  to: string;
  subject: string;
  body: string;
  cc?: string;
  bcc?: string;
  body_html?: string | null;
}

export interface EmailAttachment {
  filename: string;
  content_type: string;
  data: string;
}

export interface SendEmailPayload {
  account_id?: number;
  cc?: string;
  bcc?: string;
  body_html?: string | null;
  attachments?: EmailAttachment[];
  to: string;
  subject: string;
  body: string;
  attachment?: EmailAttachment;
}

export interface SendEmailResponse {
  message: string;
  message_id: string;
}

export type ThreadComposeMode = 'reply' | 'reply_all' | 'forward';

export interface ThreadComposePreview {
  mode: ThreadComposeMode;
  to: string[];
  cc: string[];
  subject: string;
  body: string;
  context_hash: string;
  original_attachments: number;
}

export interface ThreadSendPayload {
  mode: ThreadComposeMode;
  context_hash: string;
  to: string[];
  cc: string[];
  body: string;
  attachment?: EmailAttachment;
}

export interface ThreadSendResponse { message_id: string; threaded: boolean }
