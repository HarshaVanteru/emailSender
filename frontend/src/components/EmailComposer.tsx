import React, { useState, useRef } from 'react';
import {
  Send,
  X,
  FileText,
  Copy,
  Check,
  RotateCcw,
  MailCheck,
  AlertCircle,
  Paperclip,
} from 'lucide-react';
import type { GeneratedEmail, SendEmailPayload } from '../types';
import { readFileAsBase64, sendEmail } from '../api';

interface EmailComposerProps {
  draft: GeneratedEmail;
  onChangeDraft: (updated: Partial<GeneratedEmail>) => void;
  onResetDraft: () => void;
  onSentSuccess: (messageId: string) => void;
  isGmailConnected: boolean;
}

export const EmailComposer: React.FC<EmailComposerProps> = ({
  draft,
  onChangeDraft,
  onResetDraft,
  onSentSuccess,
  isGmailConnected,
}) => {
  const [attachment, setAttachment] = useState<File | null>(null);
  const [isSending, setIsSending] = useState(false);
  const [sendSuccessId, setSendSuccessId] = useState<string | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [viewMode, setViewMode] = useState<'edit' | 'preview'>('edit');
  const fileInputRef = useRef<HTMLInputElement>(null);

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files[0]) {
      setAttachment(e.target.files[0]);
    }
  };

  const handleRemoveAttachment = () => {
    setAttachment(null);
    if (fileInputRef.current) {
      fileInputRef.current.value = '';
    }
  };

  const handleCopy = async () => {
    const text = `To: ${draft.to}\nSubject: ${draft.subject}\n\n${draft.body}`;
    await navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const handleSend = async () => {
    if (!draft.to.trim() || !draft.subject.trim() || !draft.body.trim()) {
      setErrorMessage('Please fill in recipient, subject, and body.');
      return;
    }

    setIsSending(true);
    setErrorMessage(null);
    setSendSuccessId(null);

    try {
      const payload: SendEmailPayload = {
        to: draft.to.trim(),
        subject: draft.subject.trim(),
        body: draft.body.trim(),
      };

      if (attachment) {
        payload.attachment = {
          filename: attachment.name,
          content_type: attachment.type || 'application/octet-stream',
          data: await readFileAsBase64(attachment),
        };
      }

      const result = await sendEmail(payload);
      setSendSuccessId(result.message_id);
      onSentSuccess(result.message_id);
    } catch (err: any) {
      setErrorMessage(err.message || 'Failed to dispatch email.');
    } finally {
      setIsSending(false);
    }
  };

  const formatFileSize = (bytes: number) => {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  };

  const wordCount = draft.body.trim() ? draft.body.trim().split(/\s+/).length : 0;
  const isFormValid = draft.to.trim().length > 0 && draft.subject.trim().length > 0 && draft.body.trim().length > 0;

  return (
    <div className="flex flex-col h-full bg-white select-none">
      {/* Top Toolbar */}
      <div className="h-10 px-5 border-b border-zinc-200 flex items-center justify-between shrink-0 bg-white">
        <div className="flex items-center gap-3">
          {/* Minimal tab buttons */}
          <div className="flex items-center gap-1">
            <button
              onClick={() => setViewMode('edit')}
              className={`px-2 py-0.5 rounded text-xs font-medium transition-colors cursor-pointer ${
                viewMode === 'edit'
                  ? 'bg-zinc-100 text-zinc-900'
                  : 'text-zinc-500 hover:text-zinc-800'
              }`}
            >
              Edit
            </button>
            <button
              onClick={() => setViewMode('preview')}
              className={`px-2 py-0.5 rounded text-xs font-medium transition-colors cursor-pointer ${
                viewMode === 'preview'
                  ? 'bg-zinc-100 text-zinc-900'
                  : 'text-zinc-500 hover:text-zinc-800'
              }`}
            >
              Preview
            </button>
          </div>

          <span className="text-[11px] text-zinc-400 font-mono hidden sm:inline">
            {wordCount} words
          </span>
        </div>

        <div className="flex items-center gap-1.5">
          <button
            onClick={handleCopy}
            className="flex items-center gap-1 text-[11px] text-zinc-600 hover:text-zinc-900 px-2 py-0.5 rounded hover:bg-zinc-100 transition-colors cursor-pointer"
            title="Copy draft"
          >
            {copied ? <Check className="w-3 h-3 text-emerald-600" /> : <Copy className="w-3 h-3 text-zinc-400" />}
            <span>{copied ? 'Copied' : 'Copy'}</span>
          </button>

          <button
            onClick={onResetDraft}
            className="flex items-center gap-1 text-[11px] text-zinc-400 hover:text-rose-600 px-2 py-0.5 rounded hover:bg-zinc-100 transition-colors cursor-pointer"
            title="Reset fields"
          >
            <RotateCcw className="w-3 h-3" />
            <span>Reset</span>
          </button>
        </div>
      </div>

      {/* Notifications */}
      {sendSuccessId && (
        <div className="mx-5 mt-3 p-2.5 rounded-md bg-emerald-50 border border-emerald-200 text-emerald-900 flex items-center justify-between text-xs select-text">
          <div className="flex items-center gap-2">
            <MailCheck className="w-3.5 h-3.5 text-emerald-600 shrink-0" />
            <span>Sent. ID: <code className="font-mono">{sendSuccessId}</code></span>
          </div>
          <button onClick={() => setSendSuccessId(null)} className="text-emerald-700 hover:text-emerald-950 p-0.5 cursor-pointer">
            <X className="w-3.5 h-3.5" />
          </button>
        </div>
      )}

      {errorMessage && (
        <div className="mx-5 mt-3 p-2.5 rounded-md bg-rose-50 border border-rose-200 text-rose-900 flex items-center justify-between text-xs select-text">
          <div className="flex items-center gap-2">
            <AlertCircle className="w-3.5 h-3.5 text-rose-600 shrink-0" />
            <span>{errorMessage}</span>
          </div>
          <button onClick={() => setErrorMessage(null)} className="text-rose-700 hover:text-rose-950 p-0.5 cursor-pointer">
            <X className="w-3.5 h-3.5" />
          </button>
        </div>
      )}

      {/* Main Canvas */}
      <div className="flex-1 overflow-y-auto px-6 py-4 space-y-3 select-text">
        {viewMode === 'edit' ? (
          <div className="space-y-2.5 max-w-3xl">
            {/* To */}
            <div className="flex items-center gap-2 border-b border-zinc-100 pb-2">
              <span className="w-16 font-mono text-[11px] text-zinc-400 select-none">To</span>
              <input
                id="recipient"
                type="email"
                placeholder="recipient@example.com"
                value={draft.to}
                onChange={(e) => onChangeDraft({ to: e.target.value })}
                className="flex-1 text-xs sm:text-sm text-zinc-900 placeholder-zinc-300 focus:outline-hidden font-normal"
              />
            </div>

            {/* Subject */}
            <div className="flex items-center gap-2 border-b border-zinc-100 pb-2">
              <span className="w-16 font-mono text-[11px] text-zinc-400 select-none">Subject</span>
              <input
                id="subject"
                type="text"
                placeholder="Subject line"
                value={draft.subject}
                onChange={(e) => onChangeDraft({ subject: e.target.value })}
                className="flex-1 text-xs sm:text-sm font-medium text-zinc-900 placeholder-zinc-300 focus:outline-hidden"
              />
            </div>

            {/* Body */}
            <div className="pt-2">
              <textarea
                rows={16}
                placeholder="Draft message content..."
                value={draft.body}
                onChange={(e) => onChangeDraft({ body: e.target.value })}
                className="w-full text-xs sm:text-sm leading-relaxed text-zinc-800 placeholder-zinc-300 focus:outline-hidden resize-none bg-transparent font-normal"
              />
            </div>

            {/* Attachment */}
            <div className="pt-2 border-t border-zinc-100">
              <input
                type="file"
                ref={fileInputRef}
                onChange={handleFileChange}
                accept=".pdf,.doc,.docx,.png,.jpg,.jpeg"
                className="hidden"
              />

              {attachment ? (
                <div className="inline-flex items-center gap-2 bg-zinc-50 border border-zinc-200 rounded-md px-2.5 py-1 text-xs text-zinc-700">
                  <FileText className="w-3.5 h-3.5 text-zinc-600" />
                  <span className="font-medium text-zinc-900">{attachment.name}</span>
                  <span className="text-zinc-400 font-mono text-[10px]">({formatFileSize(attachment.size)})</span>
                  <button
                    onClick={handleRemoveAttachment}
                    className="ml-1 text-zinc-400 hover:text-rose-600 p-0.5 rounded cursor-pointer"
                    title="Remove"
                  >
                    <X className="w-3 h-3" />
                  </button>
                </div>
              ) : (
                <button
                  type="button"
                  onClick={() => fileInputRef.current?.click()}
                  className="inline-flex items-center gap-1.5 text-xs text-zinc-500 hover:text-zinc-900 px-2 py-1 rounded hover:bg-zinc-50 transition-colors cursor-pointer select-none"
                >
                  <Paperclip className="w-3 h-3 text-zinc-400" />
                  <span>Attach document</span>
                </button>
              )}
            </div>
          </div>
        ) : (
          /* Preview Mode */
          <div className="space-y-3 max-w-2xl py-2">
            <div className="border-b border-zinc-100 pb-2.5 space-y-1">
              <div className="text-xs text-zinc-400">
                To: <span className="text-zinc-800 font-mono">{draft.to || '—'}</span>
              </div>
              <h1 className="text-base font-semibold text-zinc-900">
                {draft.subject || 'No subject'}
              </h1>
            </div>

            <div className="text-xs sm:text-sm text-zinc-800 leading-relaxed whitespace-pre-wrap font-sans min-h-[220px]">
              {draft.body || <span className="text-zinc-300 italic">No content</span>}
            </div>

            {attachment && (
              <div className="pt-2 border-t border-zinc-100 text-xs text-zinc-600 flex items-center gap-2">
                <FileText className="w-3.5 h-3.5 text-zinc-600" />
                <span>{attachment.name} ({formatFileSize(attachment.size)})</span>
              </div>
            )}
          </div>
        )}
      </div>

      {/* Action Footer */}
      <div className="h-11 border-t border-zinc-200 px-5 flex items-center justify-between bg-white shrink-0">
        <div>
          {!isGmailConnected && (
            <span className="text-amber-600 text-xs flex items-center gap-1 font-medium">
              <AlertCircle className="w-3 h-3 text-amber-500" />
              Gmail disconnected
            </span>
          )}
        </div>

        <div className="flex items-center gap-2">
          <button
            onClick={onResetDraft}
            className="text-xs font-medium text-zinc-500 hover:text-zinc-800 px-2.5 py-1 rounded hover:bg-zinc-100 transition-colors cursor-pointer"
          >
            Clear
          </button>

          <button
            onClick={handleSend}
            disabled={isSending || !isFormValid}
            className="inline-flex items-center gap-1.5 bg-zinc-900 hover:bg-zinc-800 disabled:bg-zinc-200 text-white disabled:text-zinc-400 text-xs font-medium px-3.5 py-1.5 rounded-md transition-all cursor-pointer disabled:cursor-not-allowed shadow-2xs"
          >
            {isSending ? (
              <>
                <div className="w-3 h-3 border-2 border-white/30 border-t-white rounded-full animate-spin"></div>
                <span>Sending...</span>
              </>
            ) : (
              <>
                <span>Send</span>
                <Send className="w-3 h-3" />
              </>
            )}
          </button>
        </div>
      </div>
    </div>
  );
};
