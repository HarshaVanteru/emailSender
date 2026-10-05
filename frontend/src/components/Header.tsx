import React from 'react';
import { Mail, RefreshCw, ExternalLink, AlertCircle, Settings, Sun, Moon } from 'lucide-react';
import type { GmailProfile } from '../types';
import { getGmailAuthUrl } from '../api';

interface HeaderProps {
  profile: GmailProfile | null;
  checkingAuth: boolean;
  onRefreshAuth: () => void;
  onOpenSettings?: () => void;
  isDarkMode: boolean;
  onToggleTheme: () => void;
}

export const Header: React.FC<HeaderProps> = ({ profile, checkingAuth, onRefreshAuth, onOpenSettings, isDarkMode, onToggleTheme }) => {
  return (
    <header className="h-11 border-b border-zinc-200 bg-white px-4 flex items-center justify-between shrink-0 select-none dark:border-zinc-800 dark:bg-zinc-950">
      {/* Brand & Breadcrumb */}
      <div className="flex items-center gap-2.5">
        <div className="w-6 h-6 rounded-md bg-zinc-900 text-white flex items-center justify-center dark:bg-zinc-100 dark:text-zinc-900">
          <Mail className="w-3.5 h-3.5" />
        </div>
        <div className="flex items-center gap-2 text-xs">
          <span className="font-semibold text-zinc-900 tracking-tight dark:text-zinc-100">Email Studio</span>
          <span className="text-zinc-300 dark:text-zinc-700">/</span>
          <span className="text-zinc-500 font-mono text-[11px] dark:text-zinc-400">v1.0</span>
        </div>
      </div>

      {/* Account Status */}
      <div className="flex items-center gap-2">
        <button
          onClick={onToggleTheme}
          aria-label="Dark mode"
          aria-pressed={isDarkMode}
          title={`Switch to ${isDarkMode ? 'light' : 'dark'} mode`}
          className="text-zinc-500 hover:text-zinc-900 hover:bg-zinc-100 p-1.5 rounded-md cursor-pointer transition-colors dark:text-zinc-400 dark:hover:bg-zinc-800 dark:hover:text-zinc-100"
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
              <span className="w-1.5 h-1.5 rounded-full bg-emerald-500"></span>
              <span className="font-mono max-w-[200px] truncate" title={profile.email}>
                {profile.email}
              </span>
              <button
                onClick={onRefreshAuth}
                title="Refresh connection"
                className="text-zinc-400 hover:text-zinc-700 p-0.5 rounded cursor-pointer transition-colors dark:hover:text-zinc-200"
              >
                <RefreshCw className="w-3 h-3" />
              </button>
            </div>
            {onOpenSettings && (
              <button 
                onClick={onOpenSettings}
                title="Profile Settings"
                className="text-zinc-500 hover:text-zinc-900 bg-zinc-50 border border-zinc-200 p-1.5 rounded-md cursor-pointer transition-colors dark:border-zinc-800 dark:bg-zinc-900 dark:text-zinc-400 dark:hover:text-zinc-100"
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
              <span>Connect</span>
              <ExternalLink className="w-3 h-3" />
            </a>
          </div>
        )}
      </div>
    </header>
  );
};
