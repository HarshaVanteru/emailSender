export interface MailLabel { id: string; name: string; type: string }

export interface MailSummary {
  id: number;
  account_id: number;
  thread_id: number;
  from_address: string;
  subject: string;
  snippet: string;
  internal_date: number;
  labels: string[];
  has_attachments: boolean;
  ai_importance?: 'critical' | 'high' | 'normal' | 'low' | null;
  ai_is_spam?: boolean | null;
  ai_category?: string | null;
  ai_reason?: string | null;
}

export interface MailDetail extends MailSummary {
  to_addresses: { name: string; email: string }[];
  cc_addresses: { name: string; email: string }[];
  body_text: string | null;
  body_html: string | null;
  attachments: { id: number; filename: string; mime_type: string; size_bytes: number }[];
}

export interface MailPage<T> { items: T[]; next_page_token: string | null }

export interface ThreadPage extends MailPage<MailDetail> { id: number; account_id: number; subject: string }
