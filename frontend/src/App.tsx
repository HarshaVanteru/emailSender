import React, { useState, useEffect } from 'react';
import { Header } from './components/Header';
import { AiCopilot } from './components/AiCopilot';
import { EmailComposer } from './components/EmailComposer';
import type { ChatMessage, GeneratedEmail, GmailProfile } from './types';
import { fetchGmailProfile, generateEmailDraft, setToken } from './api';
import { Bot, Mail } from 'lucide-react';
import { ProfileSettings } from './components/ProfileSettings';

const INITIAL_DRAFT: GeneratedEmail = {
  to: '',
  subject: '',
  body: '',
};

export const App: React.FC = () => {
  const [profile, setProfile] = useState<GmailProfile | null>(null);
  const [checkingAuth, setCheckingAuth] = useState(true);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [draft, setDraft] = useState<GeneratedEmail>(INITIAL_DRAFT);
  const [isGenerating, setIsGenerating] = useState(false);
  const [mobileTab, setMobileTab] = useState<'copilot' | 'composer'>('copilot');
  const [showSettings, setShowSettings] = useState(false);

  const checkAuth = async () => {
    setCheckingAuth(true);
    
    // Check for token in URL
    const urlParams = new URLSearchParams(window.location.search);
    const token = urlParams.get('token');
    if (token) {
      setToken(token);
      // clean up URL
      window.history.replaceState({}, document.title, window.location.pathname);
    }

    const res = await fetchGmailProfile();
    setProfile(res);
    setCheckingAuth(false);
  };

  useEffect(() => {
    checkAuth();
  }, []);

  const handleGenerate = async (instruction: string) => {
    const updatedMessages: ChatMessage[] = [
      ...messages,
      { role: 'user', content: instruction },
    ];
    setMessages(updatedMessages);
    setIsGenerating(true);

    try {
      const response = await generateEmailDraft(instruction, updatedMessages);
      if (response.needs_clarification && response.question) {
        setMessages((prev) => [
          ...prev,
          {
            role: 'assistant',
            content: response.question!,
          },
        ]);
      } else if (response.draft) {
        setDraft({
          to: response.draft.to || '',
          subject: response.draft.subject || '',
          body: response.draft.body || '',
        });
        setMessages((prev) => [
          ...prev,
          {
            role: 'assistant',
            content:
              response.message ||
              `Draft generated for "${response.draft?.to || 'recipient'}" with subject "${response.draft?.subject}".`,
          },
        ]);
        if (window.innerWidth < 1024) {
          setMobileTab('composer');
        }
      } else if (response.message) {
        setMessages((prev) => [
          ...prev,
          {
            role: 'assistant',
            content: response.message!,
          },
        ]);
      }
    } catch (err: any) {
      setMessages((prev) => [
        ...prev,
        {
          role: 'assistant',
          content: `Failed to process request: ${err.message}`,
        },
      ]);
    } finally {
      setIsGenerating(false);
    }
  };

  const handleApplyRefinePrompt = (refineInstruction: string) => {
    const fullInstruction = `Please revise the draft: "${refineInstruction}".\nCurrent draft details:\nTo: ${draft.to}\nSubject: ${draft.subject}\nBody:\n${draft.body}`;
    handleGenerate(fullInstruction);
  };

  const handleUpdateDraft = (updated: Partial<GeneratedEmail>) => {
    setDraft((prev) => ({ ...prev, ...updated }));
  };

  const handleResetDraft = () => {
    setDraft(INITIAL_DRAFT);
  };

  const handleClearChat = () => {
    setMessages([]);
  };

  const handleSentSuccess = (messageId: string) => {
    setMessages((prev) => [
      ...prev,
      {
        role: 'assistant',
        content: `Email sent successfully (Google Message ID: ${messageId})`,
      },
    ]);
  };

  const hasActiveDraft = Boolean(draft.to || draft.subject || draft.body);

  return (
    <div className="h-screen w-screen flex flex-col bg-white overflow-hidden text-zinc-900">
      <Header
        profile={profile}
        checkingAuth={checkingAuth}
        onRefreshAuth={checkAuth}
        onOpenSettings={() => setShowSettings(true)}
      />

      {showSettings && (
        <ProfileSettings 
          profile={profile} 
          onClose={() => setShowSettings(false)} 
          onUpdate={checkAuth} 
        />
      )}

      {/* Mobile Tab Toggle */}
      <div className="lg:hidden flex border-b border-zinc-200 bg-white px-3 py-1 gap-2 shrink-0">
        <button
          onClick={() => setMobileTab('copilot')}
          className={`flex-1 flex items-center justify-center gap-1.5 py-1.5 text.xs font-medium rounded transition-colors ${
            mobileTab === 'copilot'
              ? 'bg-zinc-900 text-white'
              : 'text-zinc-600 hover:bg-zinc-100'
          }`}
        >
          <Bot className="w-3.5 h-3.5" />
          <span>Copilot</span>
        </button>
        <button
          onClick={() => setMobileTab('composer')}
          className={`flex-1 flex items-center justify-center gap-1.5 py-1.5 text.xs font-medium rounded transition-colors ${
            mobileTab === 'composer'
              ? 'bg-zinc-900 text-white'
              : 'text-zinc-600 hover:bg-zinc-100'
          }`}
        >
          <Mail className="w-3.5 h-3.5" />
          <span>Composer {hasActiveDraft && ' '}</span>
        </button>
      </div>

      {/* Edge-to-Edge Studio Workspace */}
      <main className="flex-1 flex overflow-hidden">
        {/* Left Column: AI Copilot */}
        <div
          className={`w-full lg:w-[350px] xl:w-[380px] shrink-0 h-full ${
            mobileTab === 'copilot' ? 'block' : 'hidden lg:block'
          }`}
        >
          <AiCopilot
            messages={messages}
            isGenerating={isGenerating}
            onGenerate={handleGenerate}
            onClearChat={handleClearChat}
            hasActiveDraft={hasActiveDraft}
            onApplyRefinePrompt={handleApplyRefinePrompt}
          />
        </div>

        {/* Right Column: Email Composer */}
        <div
          className={`flex-1 h-full min-w-0 ${
            mobileTab === 'composer' ? 'block' : 'hidden lg:block'
          }`}
        >
          <EmailComposer
            draft={draft}
            onChangeDraft={handleUpdateDraft}
            onResetDraft={handleResetDraft}
            onSentSuccess={handleSentSuccess}
            isGmailConnected={Boolean(profile?.email)}
          />
        </div>
      </main>
    </div>
  );
};

export default App;
