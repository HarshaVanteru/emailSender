export interface ChatMessage {
  role: 'user' | 'assistant';
  content: string;
}

export interface GeneratedEmail {
  to: string;
  subject: string;
  body: string;
}

export interface EmailAttachment {
  filename: string;
  content_type: string;
  data: string;
}

export interface SendEmailPayload {
  to: string;
  subject: string;
  body: string;
  attachment?: EmailAttachment;
}

export interface GmailProfile {
  email: string;
  is_connected: boolean;
  requires_reauth?: boolean;
  name?: string;
  signature?: string;
  preferences?: string;
  bio?: string;
}

export interface ConnectedAccount {
  id: number;
  email: string;
  is_connected: boolean;
  requires_reauth: boolean;
}

export interface CopilotResponse {
  needs_clarification: boolean;
  question?: string | null;
  draft?: GeneratedEmail | null;
  message?: string | null;
}

export interface SendEmailResponse {
  message: string;
  message_id: string;
}
