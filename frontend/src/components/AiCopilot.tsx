import React, { useState, useRef, useEffect } from 'react';
import { Sparkles, Trash2, Bot, ArrowUp } from 'lucide-react';
import type { ChatMessage } from '../types';

interface AiCopilotProps {
  messages: ChatMessage[];
  isGenerating: boolean;
  onGenerate: (instruction: string) => Promise<void>;
  onClearChat: () => void;
  hasActiveDraft: boolean;
  onApplyRefinePrompt: (refineInstruction: string) => void;
}

const STARTER_PROMPTS = [
  'Job application for Software Engineer role',
  'Polite follow-up after interview',
  'Weekly project status update to manager',
  'Request a 30-min meeting next week',
];

const REFINE_CHIPS = [
  { label: 'Shorter', instruction: 'Make it more concise, punchy, and direct' },
  { label: 'Professional', instruction: 'Rewrite with a confident, professional executive tone' },
  { label: 'Bullet points', instruction: 'Organize key points into clean bullet points' },
  { label: 'Friendly', instruction: 'Make the tone warm, approachable, and conversational' },
];

export const AiCopilot: React.FC<AiCopilotProps> = ({
  messages,
  isGenerating,
  onGenerate,
  onClearChat,
  hasActiveDraft,
  onApplyRefinePrompt,
}) => {
  const [input, setInput] = useState('');
  const chatEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, isGenerating]);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!input.trim() || isGenerating) return;
    const query = input.trim();
    setInput('');
    onGenerate(query);
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSubmit(e);
    }
  };

  return (
    <div className="flex flex-col h-full bg-zinc-50/60 border-r border-zinc-200 select-none dark:border-zinc-800 dark:bg-zinc-900/60">
      {/* Sidebar Header */}
      <div className="h-10 px-3.5 border-b border-zinc-200 flex items-center justify-between bg-white shrink-0 dark:border-zinc-800 dark:bg-zinc-950">
        <div className="flex items-center gap-1.5">
          <Sparkles className="w-3.5 h-3.5 text-zinc-700 dark:text-zinc-300" />
          <span className="text-xs font-semibold text-zinc-900 dark:text-zinc-100">Copilot</span>
        </div>

        {messages.length > 0 && (
          <button
            onClick={onClearChat}
            className="text-[11px] text-zinc-400 hover:text-zinc-700 p-1 rounded transition-colors cursor-pointer flex items-center gap-1 dark:hover:text-zinc-200"
            title="Clear conversation"
          >
            <Trash2 className="w-3 h-3" />
            <span>Clear</span>
          </button>
        )}
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto p-3.5 space-y-2.5 select-text">
        {messages.length === 0 ? (
          <div className="h-full flex flex-col justify-center items-center text-center p-2 space-y-3">
            <p className="text-xs text-zinc-400">Select a prompt template or write below</p>

            <div className="w-full space-y-1 max-w-xs pt-1">
              {STARTER_PROMPTS.map((prompt) => (
                <button
                  key={prompt}
                  onClick={() => {
                    setInput(prompt);
                    inputRef.current?.focus();
                  }}
                  className="w-full text-left p-2 rounded-md bg-white hover:bg-zinc-100/70 border border-zinc-200/90 text-xs text-zinc-700 transition-colors cursor-pointer shadow-2xs dark:border-zinc-800 dark:bg-zinc-900 dark:text-zinc-300 dark:hover:bg-zinc-800"
                >
                  {prompt}
                </button>
              ))}
            </div>
          </div>
        ) : (
          messages.map((msg, index) => {
            const isUser = msg.role === 'user';
            return (
              <div
                key={index}
                className={`flex gap-1.5 text-xs leading-relaxed ${isUser ? 'justify-end' : 'justify-start'}`}
              >
                {!isUser && (
                  <div className="w-4.5 h-4.5 rounded bg-zinc-200 text-zinc-700 flex items-center justify-center shrink-0 mt-0.5 dark:bg-zinc-800 dark:text-zinc-300">
                    <Bot className="w-3 h-3" />
                  </div>
                )}
                <div
                  className={`max-w-[88%] rounded-md px-3 py-2 whitespace-pre-wrap leading-relaxed ${
                    isUser
                      ? 'bg-zinc-900 text-white dark:bg-zinc-100 dark:text-zinc-900'
                      : 'bg-white text-zinc-800 border border-zinc-200 shadow-2xs dark:border-zinc-800 dark:bg-zinc-900 dark:text-zinc-200'
                  }`}
                >
                  {msg.content}
                </div>
              </div>
            );
          })
        )}

        {isGenerating && (
          <div className="flex gap-2 text-xs items-center text-zinc-400">
            <div className="w-4.5 h-4.5 rounded bg-zinc-200 text-zinc-700 flex items-center justify-center shrink-0 dark:bg-zinc-800 dark:text-zinc-300">
              <Bot className="w-3 h-3 animate-pulse" />
            </div>
            <span className="text-[11px] font-mono">Generating draft...</span>
          </div>
        )}
        <div ref={chatEndRef} />
      </div>

      {/* Refine Chips */}
      {hasActiveDraft && (
        <div className="px-3 py-1.5 border-t border-zinc-200 bg-white dark:border-zinc-800 dark:bg-zinc-950">
          <div className="flex flex-wrap gap-1">
            {REFINE_CHIPS.map((chip, idx) => (
              <button
                key={idx}
                onClick={() => onApplyRefinePrompt(chip.instruction)}
                disabled={isGenerating}
                className="text-[10px] font-medium bg-zinc-50 hover:bg-zinc-100 border border-zinc-200 text-zinc-600 px-2 py-0.5 rounded transition-colors cursor-pointer disabled:opacity-50 dark:border-zinc-800 dark:bg-zinc-900 dark:text-zinc-300 dark:hover:bg-zinc-800"
              >
                + {chip.label}
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Input Form */}
      <form onSubmit={handleSubmit} className="p-3 border-t border-zinc-200 bg-white dark:border-zinc-800 dark:bg-zinc-950">
        <div className="relative border border-zinc-200 rounded-md focus-within:border-zinc-400 focus-within:ring-1 focus-within:ring-zinc-300 transition-all bg-white flex items-center dark:border-zinc-800 dark:bg-zinc-900 dark:focus-within:border-zinc-600 dark:focus-within:ring-zinc-700">
          <textarea
            ref={inputRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            rows={2}
            placeholder={hasActiveDraft ? "Ask AI to edit draft..." : "Describe email to generate..."}
            disabled={isGenerating}
            className="w-full resize-none p-2 text-xs text-zinc-900 placeholder-zinc-400 focus:outline-hidden disabled:opacity-50 leading-relaxed font-normal dark:bg-transparent dark:text-zinc-100 dark:placeholder-zinc-500"
          />
          <button
            type="submit"
            disabled={!input.trim() || isGenerating}
            className="m-1.5 w-6 h-6 rounded bg-zinc-900 hover:bg-zinc-800 disabled:bg-zinc-200 text-white disabled:text-zinc-400 flex items-center justify-center shrink-0 transition-colors cursor-pointer disabled:cursor-not-allowed dark:bg-zinc-100 dark:text-zinc-900 dark:hover:bg-zinc-200 dark:disabled:bg-zinc-800 dark:disabled:text-zinc-500"
            title="Generate"
          >
            <ArrowUp className="w-3 h-3" />
          </button>
        </div>
      </form>
    </div>
  );
};
