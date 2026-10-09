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
import { getGmailAuthUrl, readFileAsBase64, sendEmail } from '../api';
import { reflowEmailBody } from '../emailLayout';

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
  const updateDraft = (updated: Partial<GeneratedEmail>) => {
    setSendSuccessId(null);
    setCopied(false);
    onChangeDraft(updated);
  };

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
    const text = `To: ${draft.to}\nSubject: ${draft.subject}\n\n${reflowEmailBody(draft.body)}`;
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      setErrorMessage('Copy is unavailable. Select the text in your draft and copy it manually.');
    }
  };
  const handleReset = () => {
    if ((draft.to || draft.subject || draft.body || attachment) && !window.confirm('Clear this draft and its attachment?')) return;
    onResetDraft();
    handleRemoveAttachment();
    setSendSuccessId(null);
    setErrorMessage(null);
  };

  const handleSend = async () => {
    if (isSending) return;
    if (!isGmailConnected) {
      setErrorMessage('Connect your Gmail account before sending. Your draft is ready to keep editing.');
      return;
    }
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

  const draftBody = draft?.body || ''; const draftTo = draft?.to || ''; const draftSubject = draft?.subject || ''; const wordCount = draftBody.trim() ? draftBody.trim().split(/\s+/).length : 0;

  return (
    <section aria-label="Email composer" className="composer-panel flex flex-col h-full">
      <div className="composer-title"><div><span className="eyebrow">MAKE IT YOURS</span><h2>Your email draft</h2></div><span className="draft-badge"><span />{draftBody ? 'Draft in progress' : 'Fresh page'}</span></div>
      <form id="email-form" noValidate onSubmit={(event) => {
        event.preventDefault();
        const form = event.currentTarget;
        if (!form.checkValidity()) {
          setViewMode('edit');
          requestAnimationFrame(() => form.reportValidity());
          return;
        }
        void handleSend();
      }} className="composer-form">
      {/* Top Toolbar */}
      <div className="composer-toolbar flex items-center justify-between shrink-0">
        <div className="flex items-center gap-3">
          {/* Minimal tab buttons */}
          <div className="flex items-center gap-1">
            <button
              onClick={() => setViewMode('edit')}
              type="button"
              aria-pressed={viewMode === 'edit'}
              className={`px-2 py-0.5 rounded text-xs font-medium transition-colors cursor-pointer ${
                viewMode === 'edit'
                  ? 'bg-zinc-100 text-zinc-900 dark:bg-zinc-800 dark:text-zinc-100'
                  : 'text-zinc-500 hover:text-zinc-800 dark:hover:text-zinc-200'
              }`}
            >
              Edit
            </button>
            <button
              onClick={() => setViewMode('preview')}
              type="button"
              aria-pressed={viewMode === 'preview'}
              className={`px-2 py-0.5 rounded text-xs font-medium transition-colors cursor-pointer ${
                viewMode === 'preview'
                  ? 'bg-zinc-100 text-zinc-900 dark:bg-zinc-800 dark:text-zinc-100'
                  : 'text-zinc-500 hover:text-zinc-800 dark:hover:text-zinc-200'
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
            type="button"
            className="flex items-center gap-1 text-[11px] text-zinc-600 hover:text-zinc-900 px-2 py-0.5 rounded hover:bg-zinc-100 transition-colors cursor-pointer dark:text-zinc-400 dark:hover:bg-zinc-800 dark:hover:text-zinc-100"
            title="Copy draft"
          >
            {copied ? <Check className="w-3 h-3 text-emerald-600" /> : <Copy className="w-3 h-3 text-zinc-400" />}
            <span>{copied ? 'Copied' : 'Copy'}</span>
          </button>

          <button
            onClick={handleReset}
            type="button"
            className="flex items-center gap-1 text-[11px] text-zinc-400 hover:text-rose-600 px-2 py-0.5 rounded hover:bg-zinc-100 transition-colors cursor-pointer dark:hover:bg-zinc-800"
            title="Reset fields"
          >
            <RotateCcw className="w-3 h-3" />
            <span>Reset</span>
          </button>
        </div>
      </div>

      {/* Notifications */}
      {sendSuccessId && (
        <div role="status" className="mx-5 mt-3 p-2.5 rounded-md bg-emerald-50 border border-emerald-200 text-emerald-900 flex items-center justify-between text-xs select-text dark:border-emerald-900 dark:bg-emerald-950/50 dark:text-emerald-200">
          <div className="flex items-center gap-2">
            <MailCheck className="w-3.5 h-3.5 text-emerald-600 shrink-0" />
            <span>Your email was sent successfully.</span>
          </div>
          <button type="button" aria-label="Dismiss success message" onClick={() => setSendSuccessId(null)} className="text-emerald-700 hover:text-emerald-950 p-0.5 cursor-pointer">
            <X className="w-3.5 h-3.5" />
          </button>
        </div>
      )}

      {errorMessage && (
        <div role="alert" className="mx-5 mt-3 p-2.5 rounded-md bg-rose-50 border border-rose-200 text-rose-900 flex items-center justify-between text-xs select-text dark:border-rose-900 dark:bg-rose-950/50 dark:text-rose-200">
          <div className="flex items-center gap-2">
            <AlertCircle className="w-3.5 h-3.5 text-rose-600 shrink-0" />
            <span>{errorMessage}</span>
          </div>
          <button type="button" aria-label="Dismiss error" onClick={() => setErrorMessage(null)} className="text-rose-700 hover:text-rose-950 p-0.5 cursor-pointer">
            <X className="w-3.5 h-3.5" />
          </button>
        </div>
      )}

      {/* Main Canvas */}
      <div className="writing-canvas flex-1 overflow-y-auto select-text">
          <div hidden={viewMode !== 'edit'} className="email-paper space-y-2.5">
            {/* To */}
              <div className="flex items-center gap-2 border-b border-zinc-100 pb-2 dark:border-zinc-800">
              <label htmlFor="recipient" className="field-label">To</label>
              <input
                id="recipient"
                type="email"
                name="recipient"
                required
                autoComplete="email"
                autoCapitalize="none"
                spellCheck={false}
                placeholder="recipient@example.com"
                value={draftTo}
                onChange={(e) => updateDraft({ to: e.target.value })}
                className="flex-1 text-xs sm:text-sm text-zinc-900 placeholder-zinc-300 focus:outline-hidden font-normal dark:bg-transparent dark:text-zinc-100 dark:placeholder-zinc-600"
              />
            </div>

            {/* Subject */}
              <div className="flex items-center gap-2 border-b border-zinc-100 pb-2 dark:border-zinc-800">
              <label htmlFor="subject" className="field-label">Subject</label>
              <input
                id="subject"
                name="subject"
                required
                type="text"
                placeholder="Subject line"
                value={draftSubject}
                onChange={(e) => updateDraft({ subject: e.target.value })}
                className="flex-1 text-xs sm:text-sm font-medium text-zinc-900 placeholder-zinc-300 focus:outline-hidden dark:bg-transparent dark:text-zinc-100 dark:placeholder-zinc-600"
              />
            </div>

            {/* Body */}
            <div className="pt-2">
              <label htmlFor="email-body" className="sr-only">Message</label>
              <textarea
                id="email-body"
                name="body"
                required
                rows={16}
                placeholder={'A great email starts here.\n\nWrite your message, or let your copilot help you find the right words.'}
                value={draftBody}
                onChange={(e) => updateDraft({ body: e.target.value })}
                className="w-full text-xs sm:text-sm leading-relaxed text-zinc-800 placeholder-zinc-300 focus:outline-hidden resize-none bg-transparent font-normal dark:text-zinc-200 dark:placeholder-zinc-600"
              />
            </div>

            {/* Attachment */}
            <div className="pt-2 border-t border-zinc-100 dark:border-zinc-800">
              <input
                type="file"
                ref={fileInputRef}
                onChange={handleFileChange}
                accept=".pdf,.doc,.docx,.png,.jpg,.jpeg"
                className="hidden"
              />

              {attachment ? (
                <div className="inline-flex items-center gap-2 bg-zinc-50 border border-zinc-200 rounded-md px-2.5 py-1 text-xs text-zinc-700 dark:border-zinc-800 dark:bg-zinc-900 dark:text-zinc-300">
                  <FileText className="w-3.5 h-3.5 text-zinc-600" />
                  <span className="font-medium text-zinc-900 dark:text-zinc-100">{attachment.name}</span>
                  <span className="text-zinc-400 font-mono text-[10px]">({formatFileSize(attachment.size)})</span>
                  <button
                    type="button"
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
                  className="inline-flex items-center gap-1.5 text-xs text-zinc-500 hover:text-zinc-900 px-2 py-1 rounded hover:bg-zinc-50 transition-colors cursor-pointer select-none dark:hover:bg-zinc-900 dark:hover:text-zinc-100"
                >
                  <Paperclip className="w-3 h-3 text-zinc-400" />
                  <span>Attach document</span>
                </button>
              )}
            </div>
          </div>
        {viewMode === 'preview' && (
          /* Preview Mode */
          <div className="email-paper space-y-3 py-2">
            <div className="border-b border-zinc-100 pb-2.5 space-y-1 dark:border-zinc-800">
              <div className="text-xs text-zinc-400">
                To: <span className="text-zinc-800 font-mono dark:text-zinc-200">{draft.to || '—'}</span>
              </div>
              <h1 className="text-base font-semibold text-zinc-900 dark:text-zinc-100">
                {draft.subject || 'No subject'}
              </h1>
            </div>

            <p className="text-xs text-zinc-500">Paragraphs wrap to the reader’s screen. Spacing may vary by email app.</p>
            <div className="recipient-email-preview">
              {draft.body ? reflowEmailBody(draft.body).split('\n\n').map((paragraph, index) => (
                <p key={index}>{paragraph}</p>
              )) : <span className="text-zinc-500 italic">No content</span>}
            </div>

            {attachment && (
              <div className="pt-2 border-t border-zinc-100 text-xs text-zinc-600 flex items-center gap-2 dark:border-zinc-800 dark:text-zinc-400">
                <FileText className="w-3.5 h-3.5 text-zinc-600" />
                <span>{attachment.name} ({formatFileSize(attachment.size)})</span>
              </div>
            )}
          </div>
        )}
      </div>

      {/* Action Footer */}
      </form>
      <div className="composer-footer flex items-center justify-between shrink-0">
        <div>
          {!isGmailConnected && (
            <a href={getGmailAuthUrl()} className="connection-hint">
              <AlertCircle className="w-3 h-3 text-amber-500" />
              Connect Gmail to send
            </a>
          )}
        </div>

        <div className="flex items-center gap-2">
          <button
            onClick={handleReset}
            className="text-xs font-medium text-zinc-500 hover:text-zinc-800 px-2.5 py-1 rounded hover:bg-zinc-100 transition-colors cursor-pointer dark:hover:bg-zinc-800 dark:hover:text-zinc-200"
          >
            Clear
          </button>

          <button
            type="submit"
            form="email-form"
            disabled={isSending || !isGmailConnected}
            className="inline-flex items-center gap-1.5 bg-zinc-900 hover:bg-zinc-800 disabled:bg-zinc-200 text-white disabled:text-zinc-400 text-xs font-medium px-3.5 py-1.5 rounded-md transition-all cursor-pointer disabled:cursor-not-allowed shadow-2xs dark:bg-zinc-100 dark:text-zinc-900 dark:hover:bg-zinc-200 dark:disabled:bg-zinc-800 dark:disabled:text-zinc-500"
          >
            {isSending ? (
              <>
                <div className="w-3 h-3 border-2 border-white/30 border-t-white rounded-full animate-spin"></div>
                <span>Sending...</span>
              </>
            ) : (
              <>
                <span>Send email</span>
                <Send className="w-3 h-3" />
              </>
            )}
          </button>
        </div>
      </div>
    </section>
  );
};
