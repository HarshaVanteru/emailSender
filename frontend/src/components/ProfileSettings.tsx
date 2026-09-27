import React, { useState } from 'react';
import { updateProfile } from '../api';
import type { GmailProfile } from '../types';
import { X, Check } from 'lucide-react';

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

  const handleSave = async () => {
    setSaving(true);
    try {
      await updateProfile({ name, bio, signature, preferences });
      setSaved(true);
      onUpdate();
      setTimeout(() => setSaved(false), 2000);
    } catch (e) {
      console.error(e);
      alert('Failed to save profile');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-lg shadow-xl w-full max-w-lg overflow-hidden flex flex-col max-h-[90vh]">
        <div className="px-5 py-3.5 border-b border-zinc-200 flex justify-between items-center bg-zinc-50">
          <div>
            <h2 className="font-semibold text-zinc-900 text-sm">Settings & AI Profile</h2>
            <p className="text-[11px] text-zinc-500">Configure your personal context and AI email preferences</p>
          </div>
          <button onClick={onClose} className="text-zinc-400 hover:text-zinc-700">
            <X className="w-4 h-4" />
          </button>
        </div>
        
        <div className="p-5 space-y-4 flex-1 overflow-y-auto">
          <div>
            <label className="block text-xs font-medium text-zinc-700 mb-1">Connected Email</label>
            <input 
              type="text" 
              value={profile?.email || ''} 
              disabled 
              className="w-full text-xs font-mono border border-zinc-200 rounded px-3 py-2 bg-zinc-100 text-zinc-500" 
            />
          </div>
          
          <div>
            <label className="block text-xs font-medium text-zinc-700 mb-1">Display Name</label>
            <input 
              type="text" 
              value={name} 
              onChange={e => setName(e.target.value)}
              placeholder="e.g. Harsha Vanteru"
              className="w-full text-sm border border-zinc-200 rounded px-3 py-2 focus:ring-1 focus:ring-zinc-900 focus:border-zinc-900 outline-none" 
            />
          </div>

          <div>
            <div className="flex justify-between items-baseline mb-1">
              <label className="block text-xs font-medium text-zinc-700">Bio & Background Context</label>
              <span className="text-[10px] text-zinc-400 font-medium text-emerald-600 bg-emerald-50 px-1.5 py-0.5 rounded">AI Context Tool</span>
            </div>
            <textarea 
              value={bio} 
              onChange={e => setBio(e.target.value)}
              placeholder="e.g. Full-stack engineer with 4+ years of experience in Python, FastAPI, React, and GenAI systems. Graduated from XYZ University with honors..."
              rows={4}
              className="w-full text-sm border border-zinc-200 rounded px-3 py-2 focus:ring-1 focus:ring-zinc-900 focus:border-zinc-900 outline-none" 
            />
            <p className="text-[11px] text-zinc-500 mt-1">
              Your career summary, skills, or portfolio details. The AI fetches this on-demand when drafting emails about you.
            </p>
          </div>

          <div>
            <label className="block text-xs font-medium text-zinc-700 mb-1">AI Writing Preferences</label>
            <textarea 
              value={preferences} 
              onChange={e => setPreferences(e.target.value)}
              placeholder="e.g. Always be polite and direct. Keep emails under 120 words. No buzzwords."
              rows={3}
              className="w-full text-sm border border-zinc-200 rounded px-3 py-2 focus:ring-1 focus:ring-zinc-900 focus:border-zinc-900 outline-none" 
            />
            <p className="text-[11px] text-zinc-500 mt-1">
              Instructions for tone, style, and formatting across all generated drafts.
            </p>
          </div>

          <div>
            <label className="block text-xs font-medium text-zinc-700 mb-1">Email Signature</label>
            <textarea 
              value={signature} 
              onChange={e => setSignature(e.target.value)}
              placeholder="Best regards,\nHarsha Vanteru"
              rows={3}
              className="w-full text-sm border border-zinc-200 rounded px-3 py-2 focus:ring-1 focus:ring-zinc-900 focus:border-zinc-900 outline-none font-mono text-xs" 
            />
          </div>
        </div>

        <div className="px-5 py-3 border-t border-zinc-200 bg-zinc-50 flex justify-end gap-2">
          <button 
            onClick={onClose}
            className="px-3.5 py-1.5 text-xs font-medium text-zinc-600 hover:bg-zinc-100 rounded transition-colors"
          >
            Cancel
          </button>
          <button 
            onClick={handleSave}
            disabled={saving}
            className="px-4 py-1.5 text-xs font-medium bg-zinc-900 text-white hover:bg-zinc-800 rounded flex items-center gap-1.5 transition-colors cursor-pointer"
          >
            {saving ? 'Saving...' : saved ? <><Check className="w-3.5 h-3.5"/> Saved</> : 'Save Changes'}
          </button>
        </div>
      </div>
    </div>
  );
};
