import React, { useState, useEffect } from 'react';
import { Header } from './components/Header';
import { AiCopilot } from './components/AiCopilot';
import { EmailComposer } from './components/EmailComposer';
import type { ChatMessage, GeneratedEmail, GmailProfile } from './types';
import { fetchGmailProfile, generateEmailDraft, setToken } from './api';
import { Bot, Mail, Sparkles } from 'lucide-react';
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
  const [isDarkMode, setIsDarkMode] = useState(() => window.localStorage.getItem('email-studio-theme') === 'dark');

  const checkAuth = async () => {
    const res = await fetchGmailProfile();
    setProfile(res);
    setCheckingAuth(false);
  };

  useEffect(() => {
    let active = true;
    // Read the OAuth callback once before checking the account.
    const urlParams = new URLSearchParams(window.location.search);
    const token = urlParams.get('token');
    if (token) {
      setToken(token);
      // clean up URL
      window.history.replaceState({}, document.title, window.location.pathname);
    }

    void fetchGmailProfile().then((res) => {
      if (active) {
        setProfile(res);
        setCheckingAuth(false);
      }
    });
    return () => { active = false; };
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
    <div data-theme={isDarkMode ? 'dark' : 'light'} className="studio-shell flex flex-col overflow-hidden">
      <Header
        profile={profile}
        checkingAuth={checkingAuth}
        onRefreshAuth={() => { setCheckingAuth(true); void checkAuth(); }}
        onOpenSettings={() => setShowSettings(true)}
        isDarkMode={isDarkMode}
        onToggleTheme={() => {
          const nextTheme = !isDarkMode;
          setIsDarkMode(nextTheme);
          window.localStorage.setItem('email-studio-theme', nextTheme ? 'dark' : 'light');
        }}
      />

      {showSettings && (
        <ProfileSettings 
          profile={profile} 
          onClose={() => setShowSettings(false)} 
          onUpdate={() => { void checkAuth(); }}
        />
      )}

      <section className="workspace-intro">
        <div><p className="eyebrow">YOUR WRITING WORKSPACE</p><h1>A little less effort. A better email.</h1><p>Turn a thought into a thoughtful message. Draft, refine, and send in one place.</p></div>
        <div className="workflow-note"><Sparkles aria-hidden="true" size={16} /><span>Describe it. Make it yours. Send it.</span></div>
      </section>
      {/* Mobile Tab Toggle */}
      <div className="lg:hidden flex border-b border-zinc-200 bg-white px-3 py-1 gap-2 shrink-0 dark:border-zinc-800 dark:bg-zinc-950">
        <button
          onClick={() => setMobileTab('copilot')}
          aria-pressed={mobileTab === 'copilot'}
          className={`flex-1 flex items-center justify-center gap-1.5 py-1.5 text.xs font-medium rounded transition-colors ${
            mobileTab === 'copilot'
              ? 'bg-zinc-900 text-white dark:bg-zinc-100 dark:text-zinc-900'
              : 'text-zinc-600 hover:bg-zinc-100 dark:text-zinc-400 dark:hover:bg-zinc-800'
          }`}
        >
          <Bot className="w-3.5 h-3.5" />
          <span>Copilot</span>
        </button>
        <button
          onClick={() => setMobileTab('composer')}
          aria-pressed={mobileTab === 'composer'}
          className={`flex-1 flex items-center justify-center gap-1.5 py-1.5 text.xs font-medium rounded transition-colors ${
            mobileTab === 'composer'
              ? 'bg-zinc-900 text-white dark:bg-zinc-100 dark:text-zinc-900'
              : 'text-zinc-600 hover:bg-zinc-100 dark:text-zinc-400 dark:hover:bg-zinc-800'
          }`}
        >
          <Mail className="w-3.5 h-3.5" />
          <span>Composer {hasActiveDraft && '•'}</span>
        </button>
      </div>

      {/* Edge-to-Edge Studio Workspace */}
      <main className="studio-workspace flex-1 flex overflow-hidden">
        {/* Left Column: AI Copilot */}
        <div
          className={`copilot-column w-full lg:w-[350px] xl:w-[380px] shrink-0 h-full ${
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
          className={`composer-column flex-1 h-full min-w-0 ${
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
