import React, { useState, useEffect } from 'react';
import { Header } from '../shared/components/Header';
import { AiCopilot } from '../features/ai-assistant/AiCopilot';
import { EmailComposer } from '../features/compose-email/EmailComposer';
import type { ChatMessage } from '../features/ai-assistant/types';
import type { GeneratedEmail } from '../features/compose-email/types';
import type { GmailProfile } from '../features/profile/types';
import { fetchGmailProfile } from '../features/profile/api';
import { generateEmailDraft } from '../features/ai-assistant/api';
import { getGmailAuthUrl } from '../features/google-login/api';
import { setToken } from '../features/google-login/session';
import { ThreadChatHistoryProvider } from '../features/ai-assistant/ThreadChatHistory';
import { FloatingChat } from '../features/ai-assistant/FloatingChat';
import { ProfileSettings } from '../features/profile/ProfileSettings';
import { Mailbox } from '../features/mailbox/Mailbox';

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
  const [showSettings, setShowSettings] = useState(false);
  const [workspace, setWorkspace] = useState<'mail' | 'write'>('mail');
  const [authResult] = useState(() => {
    const fragment = new URLSearchParams(window.location.hash.slice(1));
    return {
      status: fragment.get('auth'),
      reconnectUrl: getGmailAuthUrl(true, fragment.get('mailbox_access') === 'true',
        fragment.get('modify_access') === 'true', fragment.get('draft_access') === 'true'),
    };
  });
  const authNotice = authResult.status === 'offline_access_required'
    ? 'Google did not provide ongoing access to Gmail. Reconnect and approve access on the Google consent screen.'
    : authResult.status === 'cancelled'
      ? 'Gmail connection was cancelled. You can connect again when you’re ready.' : '';
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
    const fragment = new URLSearchParams(window.location.hash.slice(1));
    const token = fragment.get('token') || urlParams.get('token');
    if (token) {
      setToken(token);
      // clean up URL
    }
    if (token || fragment.has('auth')) window.history.replaceState({}, document.title, window.location.pathname);

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
      const response = await generateEmailDraft(instruction, messages.slice(-12));
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
    <ThreadChatHistoryProvider><div data-theme={isDarkMode ? 'dark' : 'light'} className="studio-shell flex flex-col overflow-hidden">
      <Header
        profile={profile}
        checkingAuth={checkingAuth}
        onRefreshAuth={() => { setCheckingAuth(true); void checkAuth(); }}
        onOpenSettings={() => setShowSettings(true)}
        isDarkMode={isDarkMode}
        workspace={workspace}
        onWorkspaceChange={setWorkspace}
        hasActiveDraft={hasActiveDraft}
        onToggleTheme={() => {
          const nextTheme = !isDarkMode;
          setIsDarkMode(nextTheme);
          window.localStorage.setItem('email-studio-theme', nextTheme ? 'dark' : 'light');
        }}
      />

      {authNotice && <div role="status" className="px-5 py-2 text-sm text-amber-700 dark:text-amber-300">
        <p>{authNotice}</p>
        {authResult.status === 'offline_access_required' && <a href={authResult.reconnectUrl}
          className="inline-block mt-2 font-medium underline underline-offset-2">Reconnect Gmail</a>}
      </div>}

      {showSettings && (
        <ProfileSettings 
          profile={profile} 
          onClose={() => setShowSettings(false)} 
          onUpdate={() => { void checkAuth(); }}
        />
      )}

      {workspace === 'mail' && (checkingAuth ? <main className="mail-state" role="status">Checking your connection…</main> : <Mailbox key={`${profile?.email}:${profile?.is_connected}`} signedIn={Boolean(profile?.email)} onCompose={() => { setWorkspace('write'); }} />)}

      <div className="writing-workspace" style={{ display: workspace === 'write' ? 'flex' : 'none' }}>
      <main className="studio-workspace flex-1 flex overflow-hidden">
        <FloatingChat title="Writing copilot">
          <AiCopilot
            messages={messages}
            isGenerating={isGenerating}
            onGenerate={handleGenerate}
            onClearChat={handleClearChat}
            hasActiveDraft={hasActiveDraft}
            onApplyRefinePrompt={handleApplyRefinePrompt}
          />
        </FloatingChat>
        <div className="composer-column flex-1 h-full min-w-0">
          <EmailComposer
            draft={draft}
            signature={profile?.signature || ''}
            onChangeDraft={handleUpdateDraft}
            onResetDraft={handleResetDraft}
            onSentSuccess={handleSentSuccess}
            isGmailConnected={Boolean(profile?.is_connected)}
          />
        </div>
      </main>
      </div>
    </div></ThreadChatHistoryProvider>
  );
};

export default App;
