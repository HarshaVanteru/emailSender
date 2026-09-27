import React from 'react';
import { Mail, RefreshCw, ExternalLink, AlertCircle, Settings } from 'lucide-react';
import type { GmailProfile } from '../types';
import { getGmailAuthUrl } from '../api';

interface HeaderProps {
  profile: GmailProfile | null;
  checkingAuth: boolean;
  onRefreshAuth: () => void;
  onOpenSettings?: () => void;
}

export const Header: React.FC<HeaderProps> = ({ profile, checkingAuth, onRefreshAuth, onOpenSettings }) => {
  return (
    <header className="h-11 border-b border-zinc-200 bg-white px-4 flex items-center justify-between shrink-0 select-none">
      {/* Brand & Breadcrumb */}
      <div className="flex items-center gap-2.5">
        <div className="w-6 h-6 rounded-md bg-zinc-900 text-white flex items-center justify-center">
          <Mail className="w-3.5 h-3.5" />
        </div>
        <div className="flex items-center gap-2 text-xs">
          <span className="font-semibold text-zinc-900 tracking-tight">Email Studio</span>
          <span className="text-zinc-300">/</span>
          <span className="text-zinc-500 font-mono text-[11px]">v1.0</span>
        </div>
      </div>

      {/* Account Status */}
      <div className="flex items-center gap-2">
        {checkingAuth ? (
          <div className="flex items-center gap-1.5 text-[11px] text-zinc-400 bg-zinc-50 px-2 py-0.5 rounded border border-zinc-200">
            <RefreshCw className="w-3 h-3 animate-spin text-zinc-400" />
            <span>Syncing...</span>
          </div>
        ) : profile?.email ? (
          <div className="flex items-center gap-2">
            <div className="flex items-center gap-2 bg-zinc-50 border border-zinc-200 text-zinc-700 text-[11px] px-2.5 py-1 rounded-md">
              <span className="w-1.5 h-1.5 rounded-full bg-emerald-500"></span>
              <span className="font-mono max-w-[200px] truncate" title={profile.email}>
                {profile.email}
              </span>
              <button
                onClick={onRefreshAuth}
                title="Refresh connection"
                className="text-zinc-400 hover:text-zinc-700 p-0.5 rounded cursor-pointer transition-colors"
              >
                <RefreshCw className="w-3 h-3" />
              </button>
            </div>
            {onOpenSettings && (
              <button 
                onClick={onOpenSettings}
                title="Profile Settings"
                className="text-zinc-500 hover:text-zinc-900 bg-zinc-50 border border-zinc-200 p-1.5 rounded-md cursor-pointer transition-colors"
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
              className="inline-flex items-center gap-1.5 bg-zinc-900 hover:bg-zinc-800 text-white text-xs font-medium px-2.5 py-1 rounded-md transition-all cursor-pointer shadow-2xs"
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
