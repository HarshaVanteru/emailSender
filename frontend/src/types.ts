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
  name?: string;
  signature?: string;
  preferences?: string;
}

export interface SendEmailResponse {
  message: string;
  message_id: string;
}
