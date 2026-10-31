import React, { useState, useRef, useEffect } from 'react';
import { disconnectAccount, fetchConnectedAccounts, connectGmailAccount } from '../google-login/api';
import { updateProfile } from './api';
import type { ConnectedAccount } from '../google-login/types';
import type { GmailProfile } from './types';
import { X, Check } from 'lucide-react';
import { apiRequest } from '../../shared/api/client';
import { logout } from '../google-login/session';
import { AccountDiagnostics } from './AccountDiagnostics';

interface ProfileSettingsProps {
  profile: GmailProfile | null;
  onClose: () => void;
  onUpdate: () => void;
}

export const ProfileSettings: React.FC<ProfileSettingsProps> = ({ profile, onClose, onUpdate }) => {
  const [name, setName] = useState(profile?.name || '');
  const [bio, setBio] = useState(profile?.bio || '');
  const [signature, setSignature] = useState(profile?.signature || '');
  const [preferences, setPreferences] = useState(profile?.preferences || '');
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState('');
  const [accounts, setAccounts] = useState<ConnectedAccount[]>([]);
  const [loadingAccounts, setLoadingAccounts] = useState(true);
  const [connectionError, setConnectionError] = useState('');
  const [confirmDisconnect, setConfirmDisconnect] = useState<number | null>(null);
  const [disconnecting, setDisconnecting] = useState(false);
  const [connecting, setConnecting] = useState(false);
  const handleConnect = async (accountId?: number) => {
    setConnecting(true);
    setConnectionError('');
    try { await connectGmailAccount(accountId); }
    catch (error) {
      setConnectionError(error instanceof Error ? error.message : 'Could not start connection.');
      setConnecting(false);
    }
  };
  const dialogRef = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const dialog = dialogRef.current;
    dialog?.showModal();
    return () => dialog?.close();
  }, []);

  useEffect(() => {
    let active = true;
    void fetchConnectedAccounts().then((data) => { if (active) setAccounts(data); })
      .catch((error: unknown) => { if (active) setConnectionError(error instanceof Error ? error.message : 'Could not load connections.'); })
      .finally(() => { if (active) setLoadingAccounts(false); });
    return () => { active = false; };
  }, []);

  const handleDisconnect = async (accountId: number) => {
    setDisconnecting(true);
    setConnectionError('');
    try {
      await disconnectAccount(accountId);
      setAccounts((previous) => previous.map((account) => account.id === accountId
        ? { ...account, is_connected: false, requires_reauth: false } : account));
      setConfirmDisconnect(null);
      onUpdate();
    } catch (error: unknown) {
      setConnectionError(error instanceof Error ? error.message : 'Could not disconnect Gmail.');
    } finally {
      setDisconnecting(false);
    }
  };

  const handleSave = async () => {
    setSaving(true);
    setError('');
    try {
      await updateProfile({ name, bio, signature, preferences });
      setSaved(true);
      onUpdate();
      setTimeout(() => setSaved(false), 2000);
    } catch (e) {
      console.error(e);
      setError('Your settings could not be saved. Please try again.');
    } finally {
      setSaving(false);
    }
  };

  return (
    <dialog ref={dialogRef} onCancel={onClose} aria-labelledby="settings-title" className="settings-dialog">
      <div className="bg-white rounded-lg shadow-xl w-full max-w-lg overflow-hidden flex flex-col max-h-[90vh] dark:bg-zinc-900">
        <div className="px-5 py-3.5 border-b border-zinc-200 flex justify-between items-center bg-zinc-50 dark:border-zinc-800 dark:bg-zinc-950">
          <div>
            <h2 id="settings-title" className="font-semibold text-zinc-900 text-sm dark:text-zinc-100">Make your emails sound like you</h2>
            <p className="text-[11px] text-zinc-600">Configure your personal context and AI email preferences</p>
          </div>
          <button aria-label="Close settings" onClick={onClose} className="text-zinc-400 hover:text-zinc-700 dark:hover:text-zinc-200">
            <X className="w-4 h-4" />
          </button>
        </div>
        
        <div className="p-5 space-y-4 flex-1 overflow-y-auto">
          <div>
            <label htmlFor="profile-email" className="block text-xs font-medium text-zinc-700 mb-1 dark:text-zinc-300">Your account</label>
            <input 
              id="profile-email"
              type="text" 
              value={profile?.email || ''} 
              disabled 
              className="w-full text-xs font-mono border border-zinc-200 rounded px-3 py-2 bg-zinc-100 text-zinc-600 dark:border-zinc-700 dark:bg-zinc-800 dark:text-zinc-400" 
            />
          </div>

          <section aria-labelledby="gmail-connections-title" className="rounded-lg border border-zinc-200 p-3 dark:border-zinc-700">
            <h3 id="gmail-connections-title" className="text-sm font-medium">Gmail connection</h3>
            {loadingAccounts && <p role="status" className="mt-2 text-xs text-zinc-600">Loading connection…</p>}
            {connectionError && <p role="alert" className="mt-2 text-xs text-rose-600">{connectionError}</p>}
            {!loadingAccounts && accounts.map((account) => (
              <div key={account.id} className="mt-2 space-y-2">
                <p className="text-xs break-all">{account.email}</p>
                <p role="status" className="text-xs text-zinc-600">{account.is_connected ? 'Connected · Ready to send' : account.requires_reauth ? 'Access expired · Reconnect to send' : 'Disconnected'}</p>
                {(account.is_connected || account.requires_reauth) && confirmDisconnect !== account.id && (
                  <button type="button" onClick={() => setConfirmDisconnect(account.id)} className="text-xs font-medium text-rose-600">Disconnect Gmail</button>
                )}
                {confirmDisconnect === account.id && (
                  <div className="space-y-2 rounded bg-rose-50 p-3 dark:bg-rose-950">
                    <p className="text-xs">Disconnect {account.email}? This revokes Email Studio’s Google access. Your email and writing preferences stay saved.</p>
                    <div className="flex gap-3">
                      <button type="button" disabled={disconnecting} onClick={() => void handleDisconnect(account.id)} className="text-xs font-medium text-rose-700 disabled:opacity-50">{disconnecting ? 'Disconnecting…' : 'Confirm disconnect'}</button>
                      <button type="button" disabled={disconnecting} onClick={() => setConfirmDisconnect(null)} className="text-xs font-medium">Keep connected</button>
                    </div>
                  </div>
                )}
                {!account.is_connected && <button type="button" disabled={connecting} onClick={() => void handleConnect(account.id)} className="inline-block text-xs font-medium text-indigo-600">Reconnect Gmail</button>}
                <AccountDiagnostics accountId={account.id} />
              </div>
            ))}
            {!loadingAccounts && <button type="button" disabled={connecting} onClick={() => void handleConnect()} className="inline-block mt-2 text-xs text-indigo-600">{connecting ? 'Connecting...' : 'Add Gmail account'}</button>}
          </section>
          
          <div>
            <label htmlFor="profile-name" className="block text-xs font-medium text-zinc-700 mb-1 dark:text-zinc-300">Display Name</label>
            <input 
              id="profile-name"
              autoComplete="name"
              type="text" 
              value={name} 
              onChange={e => setName(e.target.value)}
              placeholder="e.g. Harsha Vanteru"
              className="w-full text-sm border border-zinc-200 rounded px-3 py-2 focus:ring-1 focus:ring-zinc-900 focus:border-zinc-900 outline-none dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-100 dark:placeholder-zinc-600 dark:focus:ring-zinc-400 dark:focus:border-zinc-400" 
            />
          </div>

          <div>
            <div className="flex justify-between items-baseline mb-1">
              <label htmlFor="profile-bio" className="block text-xs font-medium text-zinc-700 dark:text-zinc-300">Bio & Background Context</label>
              <span className="text-[10px] text-zinc-400 font-medium text-emerald-600 bg-emerald-50 px-1.5 py-0.5 rounded dark:bg-emerald-950 dark:text-emerald-300">AI Context Tool</span>
            </div>
            <textarea 
              id="profile-bio"
              value={bio} 
              onChange={e => setBio(e.target.value)}
              placeholder="e.g. Full-stack engineer with 4+ years of experience in Python, FastAPI, React, and GenAI systems. Graduated from XYZ University with honors..."
              rows={4}
              className="w-full text-sm border border-zinc-200 rounded px-3 py-2 focus:ring-1 focus:ring-zinc-900 focus:border-zinc-900 outline-none dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-100 dark:placeholder-zinc-600 dark:focus:ring-zinc-400 dark:focus:border-zinc-400" 
            />
            <p className="text-[11px] text-zinc-600 mt-1">
              Your career summary, skills, or portfolio details. The AI fetches this on-demand when drafting emails about you.
            </p>
          </div>

          <div>
            <label htmlFor="profile-preferences" className="block text-xs font-medium text-zinc-700 mb-1 dark:text-zinc-300">AI Writing Preferences</label>
            <textarea 
              id="profile-preferences"
              value={preferences} 
              onChange={e => setPreferences(e.target.value)}
              placeholder="e.g. Always be polite and direct. Keep emails under 120 words. No buzzwords."
              rows={3}
              className="w-full text-sm border border-zinc-200 rounded px-3 py-2 focus:ring-1 focus:ring-zinc-900 focus:border-zinc-900 outline-none dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-100 dark:placeholder-zinc-600 dark:focus:ring-zinc-400 dark:focus:border-zinc-400" 
            />
            <p className="text-[11px] text-zinc-600 mt-1">
              Instructions for tone, style, and formatting across all generated drafts.
            </p>
          </div>

          <div>
            <label htmlFor="profile-signature" className="block text-xs font-medium text-zinc-700 mb-1 dark:text-zinc-300">Email Signature</label>
            <textarea 
              id="profile-signature"
              value={signature} 
              onChange={e => setSignature(e.target.value)}
              placeholder="Best regards,\nHarsha Vanteru"
              rows={3}
              className="w-full text-sm border border-zinc-200 rounded px-3 py-2 focus:ring-1 focus:ring-zinc-900 focus:border-zinc-900 outline-none font-mono text-xs dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-100 dark:placeholder-zinc-600 dark:focus:ring-zinc-400 dark:focus:border-zinc-400" 
            />
          </div>
        </div>

        {error && <p role="alert" className="px-5 py-2 text-sm text-rose-600">{error}</p>}
        {saved && <p role="status" className="px-5 py-2 text-sm text-emerald-600">Your writing preferences have been saved.</p>}
        <div className="px-5 py-3 border-t border-zinc-200 bg-zinc-50 flex justify-end gap-2 dark:border-zinc-800 dark:bg-zinc-950">
          <button type="button" onClick={() => {
            void apiRequest('auth/logout', undefined, 'POST').then(() => { logout(); window.location.reload(); })
              .catch(reason => setError(reason instanceof Error ? reason.message : 'Could not sign out.'));
          }}>Sign out</button>
          <button 
            onClick={onClose}
            className="px-3.5 py-1.5 text-xs font-medium text-zinc-600 hover:bg-zinc-100 rounded transition-colors dark:text-zinc-300 dark:hover:bg-zinc-800"
          >
            Cancel
          </button>
          <button 
            onClick={handleSave}
            disabled={saving}
            className="px-4 py-1.5 text-xs font-medium bg-zinc-900 text-white hover:bg-zinc-800 rounded flex items-center gap-1.5 transition-colors cursor-pointer dark:bg-zinc-100 dark:text-zinc-900 dark:hover:bg-zinc-200"
          >
            {saving ? 'Saving...' : saved ? <><Check className="w-3.5 h-3.5"/> Saved</> : 'Save Changes'}
          </button>
        </div>
      </div>
    </dialog>
  );
};
