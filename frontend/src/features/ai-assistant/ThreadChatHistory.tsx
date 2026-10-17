import { useState, type ReactNode } from 'react';
import { ThreadChatHistory } from './threadChatContext';

export function ThreadChatHistoryProvider({ children }: { children: ReactNode }) {
  const [prompts, setPrompts] = useState<Record<string, string>>({});
  return <ThreadChatHistory.Provider value={{ prompts, remember: (key, prompt) => setPrompts(previous => ({ ...previous, [key]: prompt })) }}>{children}</ThreadChatHistory.Provider>;
}

