import { createContext, useContext } from 'react';

export const ThreadChatHistory = createContext<{
  prompts: Record<string, string>;
  remember: (key: string, prompt: string) => void;
}>({ prompts: {}, remember: () => {} });

export function useThreadChatHistory() { return useContext(ThreadChatHistory); }
