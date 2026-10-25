import React from 'react';
import { Mail, PenLine, RefreshCw, ExternalLink, AlertCircle, Settings, Sun, Moon } from 'lucide-react';
import type { GmailProfile } from '../../features/profile/types';
import { getGmailAuthUrl } from '../../features/google-login/api';

interface HeaderProps {
  profile: GmailProfile | null;
  checkingAuth: boolean;
  onRefreshAuth: () => void;
  onOpenSettings?: () => void;
  isDarkMode: boolean;
  onToggleTheme: () => void;
  workspace: 'mail' | 'write';
  onWorkspaceChange: (workspace: 'mail' | 'write') => void;
  hasActiveDraft: boolean;
}

export const Header: React.FC<HeaderProps> = ({ profile, checkingAuth, onRefreshAuth, onOpenSettings, isDarkMode, onToggleTheme, workspace, onWorkspaceChange, hasActiveDraft }) => {
  return (
    <header className="studio-header flex items-center justify-between shrink-0 select-none">
      {/* Brand & Breadcrumb */}
      <div className="flex items-center gap-2.5">
        <div className="brand-mark flex items-center justify-center">
          <Mail className="w-3.5 h-3.5" />
        </div>
        <div className="flex items-center gap-2 text-xs">
          <span className="brand-name">Email Studio</span>
        </div>
        <nav className="workspace-switch" aria-label="Workspace">
          <button type="button" aria-label="Mail" title="Mailbox" aria-current={workspace === 'mail' ? 'page' : undefined} onClick={() => onWorkspaceChange('mail')}><Mail size={17} aria-hidden="true" /><span className="workspace-label">Mail</span></button>
          <button type="button" aria-label="Write" title={hasActiveDraft ? 'Write — draft in progress' : 'Write an email'} aria-current={workspace === 'write' ? 'page' : undefined} onClick={() => onWorkspaceChange('write')}><PenLine size={17} aria-hidden="true" /><span className="workspace-label">Write</span>{hasActiveDraft && <span className="draft-dot" aria-label="Draft in progress" />}</button>
        </nav>
      </div>

      {/* Account Status */}
      <div className="flex items-center gap-2">
        <button
          onClick={onToggleTheme}
          aria-label="Dark mode"
          aria-pressed={isDarkMode}
          title={`Switch to ${isDarkMode ? 'light' : 'dark'} mode`}
          className="text-zinc-600 hover:text-zinc-900 hover:bg-zinc-100 p-1.5 rounded-md cursor-pointer transition-colors dark:text-zinc-400 dark:hover:bg-zinc-800 dark:hover:text-zinc-100"
        >
          {isDarkMode ? <Sun className="w-3.5 h-3.5" /> : <Moon className="w-3.5 h-3.5" />}
        </button>
        {checkingAuth ? (
          <div className="flex items-center gap-1.5 text-[11px] text-zinc-400 bg-zinc-50 px-2 py-0.5 rounded border border-zinc-200 dark:border-zinc-800 dark:bg-zinc-900">
            <RefreshCw className="w-3 h-3 animate-spin text-zinc-400" />
            <span>Syncing...</span>
          </div>
        ) : profile?.email ? (
          <div className="flex items-center gap-2">
            <div className="flex items-center gap-2 bg-zinc-50 border border-zinc-200 text-zinc-700 text-[11px] px-2.5 py-1 rounded-md dark:border-zinc-800 dark:bg-zinc-900 dark:text-zinc-300">
              <span aria-hidden="true" className={`w-1.5 h-1.5 rounded-full ${profile.is_connected ? 'bg-emerald-600' : 'bg-amber-600'}`}></span>
              <span className="font-mono max-w-[110px] sm:max-w-[200px] truncate" title={profile.email}>
                {profile.email}
              </span>
              <span className="sr-only">{profile.is_connected ? 'Gmail connected' : 'Gmail disconnected'}</span>
              <button
                onClick={onRefreshAuth}
                title="Refresh connection"
                aria-label="Refresh Gmail connection"
                className="text-zinc-400 hover:text-zinc-700 p-0.5 rounded cursor-pointer transition-colors dark:hover:text-zinc-200"
              >
                <RefreshCw className="w-3 h-3" />
              </button>
            </div>
            {!profile.is_connected && <a href={getGmailAuthUrl(true)} className="text-xs text-indigo-600 font-medium">Reconnect</a>}
            {onOpenSettings && (
              <button 
                onClick={onOpenSettings}
                title="Profile Settings"
                aria-label="Open profile settings"
                className="text-zinc-600 hover:text-zinc-900 bg-zinc-50 border border-zinc-200 p-1.5 rounded-md cursor-pointer transition-colors dark:border-zinc-800 dark:bg-zinc-900 dark:text-zinc-400 dark:hover:text-zinc-100"
              >
                <Settings className="w-3.5 h-3.5" />
              </button>
            )}
          </div>
        ) : (
          <div className="flex items-center gap-2">
            <span className="text-[11px] text-amber-600 flex items-center gap-1 font-medium hidden sm:flex">
              <AlertCircle className="w-3 h-3" />
              Disconnected
            </span>
            <a
              href={getGmailAuthUrl()}
              className="inline-flex items-center gap-1.5 bg-zinc-900 hover:bg-zinc-800 text-white text-xs font-medium px-2.5 py-1 rounded-md transition-all cursor-pointer shadow-2xs dark:bg-zinc-100 dark:text-zinc-900 dark:hover:bg-zinc-200"
            >
              <span>Connect Gmail</span>
              <ExternalLink className="w-3 h-3" />
            </a>
          </div>
        )}
      </div>
    </header>
  );
};
