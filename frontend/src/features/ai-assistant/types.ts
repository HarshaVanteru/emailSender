import type { GeneratedEmail } from '../compose-email/types';

export interface ChatMessage {
  role: 'user' | 'assistant';
  content: string;
}

export interface CopilotResponse {
  needs_clarification: boolean;
  question?: string | null;
  draft?: GeneratedEmail | null;
  message?: string | null;
}

export type ContextAiOperation = 'summarize' | 'generate_reply' | 'rewrite' | 'extract_actions' | 'classify';

export interface ContextAiSuggestion {
  id: number;
  message_id: number | null;
  operation: ContextAiOperation;
  created_at: string;
  result: {
    summary?: string;
    key_points?: string[];
    draft?: GeneratedEmail;
    rewritten_text?: string;
    actions?: { action: string; owner?: string | null; due_date?: string | null }[];
    category?: string;
    priority?: string;
    reason?: string;
  };
}
