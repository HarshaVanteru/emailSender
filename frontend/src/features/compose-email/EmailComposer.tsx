import { useEffect, useEffectEvent, useRef, useState } from 'react';
import { Send, Copy, RotateCcw, Paperclip, Trash2, X } from 'lucide-react';
import type { ConnectedAccount } from '../google-login/types';
import type { GeneratedEmail, SendEmailPayload } from './types';
import type { GmailDraftDetail, GmailDraftSummary } from '../drafts/types';
import { fetchConnectedAccounts, getGmailAuthUrl } from '../google-login/api';
import { discardGmailDraft, getGmailDraft, listGmailDrafts, saveGmailDraft, sendGmailDraft } from '../drafts/api';
import { readFileAsBase64, sendEmail } from './api';
import { RichTextEditor } from './RichTextEditor';
import { sanitizeComposeHtml, textToHtml } from './composeHtml';

interface EmailComposerProps {
  draft: GeneratedEmail;
  signature?: string;
  onChangeDraft: (updated: Partial<GeneratedEmail>) => void;
  onResetDraft: () => void;
  onSentSuccess: (messageId: string) => void;
  isGmailConnected: boolean;
}
interface ReviewedMessage {
  payload: SendEmailPayload;
  draftId?: string;
  contentHash?: string;
  accountId: number;
  key: string;
  filenames: string[];
}
const fingerprint = (draft: GeneratedEmail, files: File[]) => JSON.stringify([
  draft.to, draft.cc || '', draft.bcc || '', draft.subject, draft.body, draft.body_html || null,
  files.map(file => [file.name, file.type, file.size, file.lastModified]),
]);
function restoredFiles(saved: GmailDraftDetail): File[] {
  return saved.attachments.filter(item => item.data !== null).map(item => {
    const binary = atob(item.data!);
    return new File([Uint8Array.from(binary, character => character.charCodeAt(0))], item.filename, { type: item.content_type });
  });
}

export function EmailComposer({ draft, signature = '', onChangeDraft, onResetDraft, onSentSuccess, isGmailConnected }: EmailComposerProps) {
  const [files, setFiles] = useState<File[]>([]);
  const [accounts, setAccounts] = useState<ConnectedAccount[]>([]);
  const [accountId, setAccountId] = useState<number | null>(null);
  const [gmailDrafts, setGmailDrafts] = useState<GmailDraftSummary[]>([]);
  const [loadedDraft, setLoadedDraft] = useState<GmailDraftDetail | null>(null);
  const [savedKey, setSavedKey] = useState('');
  const [viewMode, setViewMode] = useState<'edit' | 'preview'>('edit');
  const [showCc, setShowCc] = useState(false);
  const [showBcc, setShowBcc] = useState(false);
  const [autosave, setAutosave] = useState(true);
  const [isSaving, setIsSaving] = useState(false);
  const [isLoadingDrafts, setIsLoadingDrafts] = useState(false);
  const [preparingReview, setPreparingReview] = useState(false);
  const [sending, setSending] = useState(false);
  const [remaining, setRemaining] = useState<number | null>(null);
  const [review, setReview] = useState<ReviewedMessage | null>(null);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [copied, setCopied] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);
  const form = useRef<HTMLFormElement>(null);
  const reviewDialog = useRef<HTMLDialogElement>(null);
  const sendingTimer = useRef<ReturnType<typeof setInterval> | null>(null);
  const saving = useRef(false);
  const selected = accounts.find(account => account.id === accountId);
  const canUseDrafts = Boolean(selected?.draft_access || selected?.modify_access);
  const currentKey = fingerprint(draft, files);
  const currentKeyRef = useRef(currentKey);
  useEffect(() => { currentKeyRef.current = currentKey; }, [currentKey]);
  const hasContent = Boolean(draft.to || draft.cc || draft.bcc || draft.subject || draft.body || files.length);
  const changed = savedKey !== currentKey;
  const busy = sending || remaining !== null || preparingReview || isLoadingDrafts;
  const readonly = busy || loadedDraft?.can_edit === false;
  const wordCount = draft.body.trim() ? draft.body.trim().split(/\s+/).length : 0;

  useEffect(() => {
    const controller = new AbortController();
    void fetchConnectedAccounts(controller.signal).then(items => {
      if (controller.signal.aborted) return;
      const connected = items.filter(item => item.is_connected && !item.requires_reauth);
      setAccounts(connected);
      setAccountId(previous => connected.some(item => item.id === previous) ? previous : connected[0]?.id ?? null);
    }).catch(() => { if (!controller.signal.aborted) setAccounts([]); });
    return () => controller.abort();
  }, [isGmailConnected]);
  useEffect(() => () => { if (sendingTimer.current) clearInterval(sendingTimer.current); }, []);
  useEffect(() => {
    if (review) reviewDialog.current?.showModal();
  }, [review]);
  useEffect(() => {
    if (remaining === null) return;
    const warn = (event: BeforeUnloadEvent) => { event.preventDefault(); event.returnValue = ''; };
    window.addEventListener('beforeunload', warn);
    return () => window.removeEventListener('beforeunload', warn);
  }, [remaining]);

  function update(value: Partial<GeneratedEmail>) {
    setNotice(''); setCopied(false); onChangeDraft(value);
  }
  async function buildPayload(): Promise<SendEmailPayload> {
    const inlineBytes = Array.from((draft.body_html || '').matchAll(/data:image\/(?:png|jpeg|gif|webp);base64,([A-Za-z0-9+/=]+)/g)).reduce((total, match) => total + Math.floor(match[1].length * 3 / 4) - (match[1].endsWith('==') ? 2 : match[1].endsWith('=') ? 1 : 0), 0);
    if (files.length > 20 || inlineBytes + files.reduce((total, file) => total + file.size, 0) > 25 * 1024 * 1024) throw new Error('Use up to 20 attachments totaling 25 MB.');
    return {
      account_id: accountId ?? undefined, to: draft.to.trim(), cc: draft.cc?.trim() || '', bcc: draft.bcc?.trim() || '',
      subject: draft.subject, body: draft.body, body_html: draft.body_html ? sanitizeComposeHtml(draft.body_html) : null,
      attachments: await Promise.all(files.map(async file => ({ filename: file.name, content_type: file.type || 'application/octet-stream', data: await readFileAsBase64(file) }))),
    };
  }
  async function loadDrafts() {
    if (!accountId) return;
    setIsLoadingDrafts(true); setError('');
    try { setGmailDrafts((await listGmailDrafts(accountId)).items); }
    catch (reason) { setError(reason instanceof Error ? reason.message : 'Could not load Gmail drafts.'); }
    finally { setIsLoadingDrafts(false); }
  }
  async function save(automatic = false, payload?: SendEmailPayload): Promise<GmailDraftDetail | null> {
    if (!accountId || !canUseDrafts || saving.current || loadedDraft?.can_edit === false) return null;
    const key = currentKey;
    saving.current = true; setIsSaving(true);
    if (!automatic) setError('');
    try {
      const content = payload || await buildPayload();
      const { account_id: _account, ...draftContent } = content;
      const result = await saveGmailDraft(accountId, { ...draftContent, ...(loadedDraft ? { content_hash: loadedDraft.content_hash } : {}) }, loadedDraft?.id);
      setLoadedDraft(result); setSavedKey(key);
      setNotice(automatic ? 'Autosaved to Gmail.' : 'Saved to Gmail Drafts.');
      return result;
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Could not save the draft. Check Gmail before retrying.');
      // Pause automatic retries after ambiguous errors to avoid duplicate drafts.
      if (automatic) setAutosave(false);
      return null;
    } finally { saving.current = false; setIsSaving(false); }
  }
  const autosaveLatest = useEffectEvent(() => { void save(true); });
  useEffect(() => {
    if (!autosave || !canUseDrafts || !hasContent || !changed || isSaving || busy || review || loadedDraft?.can_edit === false) return;
    // Incomplete recipients remain editable; don't interrupt typing with errors.
    const probe = document.createElement('input'); probe.type = 'email'; probe.multiple = true;
    for (const value of [draft.to, draft.cc, draft.bcc]) { probe.value = value || ''; if (!probe.checkValidity()) return; }
    const timer = setTimeout(autosaveLatest, 2000);
    return () => clearTimeout(timer);
  }, [autosave, canUseDrafts, hasContent, changed, isSaving, busy, review, loadedDraft?.can_edit, currentKey, draft.to, draft.cc, draft.bcc]);

  async function openDraft(id: string) {
    if (!accountId || saving.current || busy) return;
    if (hasContent && changed && !window.confirm('Discard unsaved changes and open this Gmail draft?')) return;
    setIsLoadingDrafts(true); setError('');
    try {
      const result = await getGmailDraft(accountId, id);
      const restored = restoredFiles(result);
      const content = { to: result.to, cc: result.cc, bcc: result.bcc, subject: result.subject, body: result.body, body_html: result.body_html || null };
      onChangeDraft(content); setFiles(restored); setLoadedDraft(result); setSavedKey(fingerprint(content, restored));
      setShowCc(Boolean(result.cc)); setShowBcc(Boolean(result.bcc)); setNotice(''); setViewMode(result.can_edit ? 'edit' : 'preview');
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'Could not open this draft.'); }
    finally { setIsLoadingDrafts(false); }
  }
  function clearLocal() {
    onResetDraft(); setFiles([]); setLoadedDraft(null); setSavedKey(''); setNotice(''); setError(''); setShowCc(false); setShowBcc(false);
    if (fileInput.current) fileInput.current.value = '';
  }
  function reset() {
    if (busy || saving.current) return;
    if (hasContent && !window.confirm('Clear the editor? A saved Gmail draft will remain in Gmail.')) return;
    clearLocal();
  }
  async function discard() {
    if (busy || saving.current || !window.confirm(loadedDraft ? 'Permanently discard this Gmail draft and clear the editor?' : 'Discard this unsaved draft?')) return;
    setIsLoadingDrafts(true); setError('');
    try {
      if (loadedDraft && accountId) await discardGmailDraft(accountId, loadedDraft.id, loadedDraft.content_hash);
      setGmailDrafts(items => items.filter(item => item.id !== loadedDraft?.id)); clearLocal();
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'Could not discard the draft.'); }
    finally { setIsLoadingDrafts(false); }
  }
  async function copy() {
    try {
      await navigator.clipboard.writeText(`To: ${draft.to}\n${draft.cc ? `Cc: ${draft.cc}\n` : ''}${draft.bcc ? `Bcc: ${draft.bcc}\n` : ''}Subject: ${draft.subject}\n\n${draft.body}`);
      setCopied(true);
    } catch { setError('Copy is unavailable. Select and copy the draft text manually.'); }
  }
  async function openReview() {
    if (busy || saving.current || !accountId || !isGmailConnected) return;
    if (!form.current?.reportValidity()) { setViewMode('edit'); return; }
    if (!(draft.to.trim() || draft.cc?.trim() || draft.bcc?.trim()) || !draft.body.trim() || !draft.subject.trim()) {
      setError('Complete the recipients, subject, and message before sending.'); setViewMode('edit'); return;
    }
    setPreparingReview(true); setError('');
    try {
      const payload = await buildPayload();
      let stored = loadedDraft;
      if (canUseDrafts && changed) { stored = await save(false, payload); if (!stored) return; }
      if (stored && !stored.can_edit) throw new Error('Open this draft in Gmail to review its complete content.');
      setReview({ payload, accountId, draftId: stored?.id, contentHash: stored?.content_hash, key: currentKey, filenames: files.map(file => file.name) });
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'Could not prepare the send review.'); }
    finally { setPreparingReview(false); }
  }
  async function deliver(message: ReviewedMessage) {
    setRemaining(null); setSending(true);
    try {
      const result = message.draftId && message.contentHash
        ? await sendGmailDraft(message.accountId, message.draftId, message.contentHash)
        : await sendEmail(message.payload);
      if (currentKeyRef.current === message.key) clearLocal();
      else { setLoadedDraft(null); setSavedKey(''); }
      setGmailDrafts(items => items.filter(item => item.id !== message.draftId));
      setNotice('Your email was sent successfully.'); onSentSuccess(result.message_id);
    } catch (reason) {
      setAutosave(false);
      setError(`${reason instanceof Error ? reason.message : 'Gmail could not confirm delivery.'} Check Gmail Sent before trying again.`);
    } finally { setSending(false); }
  }
  function queueSend() {
    if (!review || busy || sendingTimer.current) return;
    const message = review;
    reviewDialog.current?.close(); setReview(null); setRemaining(10); setNotice('');
    let seconds = 10;
    sendingTimer.current = setInterval(() => {
      seconds -= 1;
      if (seconds === 0) {
        if (sendingTimer.current) clearInterval(sendingTimer.current);
        sendingTimer.current = null; void deliver(message);
      } else setRemaining(seconds);
    }, 1000);
  }
  function undoSend() {
    if (sendingTimer.current) clearInterval(sendingTimer.current);
    sendingTimer.current = null; setRemaining(null); setNotice('Send cancelled. Your draft is ready to edit.');
  }
  function attach(incoming: File[]) {
    if (readonly) return;
    const updated = [...files, ...incoming];
    if (updated.length > 20 || updated.reduce((sum, file) => sum + file.size, 0) > 25 * 1024 * 1024) {
      setError('Use up to 20 attachments totaling 25 MB.'); return;
    }
    setFiles(updated); setNotice('');
    if (fileInput.current) fileInput.current.value = '';
  }

  return <section aria-label="Email composer" className="composer-panel flex flex-col h-full">
    <div className="composer-title"><div><h2>Write an email</h2></div><span className="draft-badge"><span />{hasContent ? 'Draft in progress' : 'Fresh page'}</span></div>
    <form ref={form} id="email-form" className="composer-form" onSubmit={event => { event.preventDefault(); void openReview(); }}>
      <div className="composer-toolbar flex items-center justify-between shrink-0">
        <div className="flex items-center gap-2"><button type="button" aria-pressed={viewMode === 'edit'} onClick={() => setViewMode('edit')}>Edit</button><button type="button" aria-pressed={viewMode === 'preview'} onClick={() => setViewMode('preview')}>Preview</button><span className="mail-muted text-xs">{wordCount} words</span></div>
        <div className="flex items-center gap-1"><button type="button" onClick={() => { void copy(); }}><Copy size={13} />{copied ? 'Copied' : 'Copy'}</button><button type="button" disabled={busy || isSaving} onClick={reset}><RotateCcw size={13} />Reset</button></div>
      </div>
      {error && <div className="compose-feedback error" role="alert">{error}<button type="button" aria-label="Dismiss error" onClick={() => setError('')}><X size={16} /></button></div>}
      {notice && <p className="compose-feedback" role="status">{notice}</p>}
      {remaining !== null && <div className="compose-feedback" role="status">Sending in {remaining}s. Keep this tab open.<button type="button" onClick={undoSend}>Undo send</button></div>}
      {sending && <p className="compose-feedback" role="status">Sending to Gmail...</p>}
      <div className="composer-account flex flex-wrap items-center gap-2 text-xs">
        <label htmlFor="draft-account">Gmail account</label><select id="draft-account" value={accountId ?? ''} disabled={busy || isSaving} onChange={event => {
          if (hasContent && !window.confirm('Switch accounts and clear the editor? Saved Gmail drafts will remain in Gmail.')) return;
          clearLocal(); setAccountId(Number(event.target.value)); setGmailDrafts([]);
        }}><option value="" disabled>Choose account</option>{accounts.map(account => <option key={account.id} value={account.id}>{account.email}</option>)}</select>
        {canUseDrafts ? <><button type="button" disabled={busy || isSaving} onClick={() => { void loadDrafts(); }}>Gmail drafts</button><label className="compose-autosave"><input type="checkbox" checked={autosave} disabled={busy} onChange={event => setAutosave(event.target.checked)} />Autosave</label><span role="status">{isSaving ? 'Saving...' : hasContent && changed ? 'Unsaved changes' : loadedDraft ? 'Saved' : ''}</span></>
          : selected && <a href={getGmailAuthUrl(true, false, false, true)}>Enable draft autosave</a>}
      </div>
      {gmailDrafts.length > 0 && <div aria-label="Gmail drafts" className="compose-draft-list">{gmailDrafts.map(item => <button key={item.id} type="button" disabled={busy || isSaving} onClick={() => { void openDraft(item.id); }}>{item.subject || '(No subject)'} - {item.to || '(No recipient)'}</button>)}</div>}
      {loadedDraft?.can_edit === false && <p className="compose-feedback">This external draft contains content this editor cannot preserve. <a href="https://mail.google.com/mail/u/0/#drafts" target="_blank" rel="noopener noreferrer">Open in Gmail</a></p>}
      <div className="writing-canvas flex-1 overflow-y-auto select-text" onDragOver={event => { event.preventDefault(); }} onDrop={event => { event.preventDefault(); attach(Array.from(event.dataTransfer.files)); }}>
        <div className="email-paper space-y-2.5">
          <div className="composer-field flex items-center gap-2"><label htmlFor="recipient" className="field-label">To</label><input id="recipient" type="email" multiple required={!draft.cc && !draft.bcc} autoComplete="email" autoCapitalize="none" spellCheck={false} value={draft.to} placeholder="Recipients, separated by commas" disabled={readonly} onChange={event => update({ to: event.target.value })} className="flex-1 min-w-0" /><button type="button" aria-expanded={showCc || Boolean(draft.cc)} onClick={() => setShowCc(value => !value)}>Cc</button><button type="button" aria-expanded={showBcc || Boolean(draft.bcc)} onClick={() => setShowBcc(value => !value)}>Bcc</button></div>
          {(showCc || draft.cc) && <div className="composer-field flex items-center gap-2"><label htmlFor="compose-cc" className="field-label">Cc</label><input id="compose-cc" type="email" multiple value={draft.cc || ''} disabled={readonly} placeholder="Cc recipients" className="flex-1 min-w-0" onChange={event => update({ cc: event.target.value })} /></div>}
          {(showBcc || draft.bcc) && <div className="composer-field flex items-center gap-2"><label htmlFor="compose-bcc" className="field-label">Bcc</label><input id="compose-bcc" type="email" multiple value={draft.bcc || ''} disabled={readonly} placeholder="Bcc recipients" className="flex-1 min-w-0" onChange={event => update({ bcc: event.target.value })} /></div>}
          <div className="composer-field flex items-center gap-2"><label htmlFor="subject" className="field-label">Subject</label><input id="subject" required maxLength={998} value={draft.subject} disabled={readonly} placeholder="Give your message a subject" className="flex-1 min-w-0" onChange={event => update({ subject: event.target.value })} /></div>
          <div hidden={viewMode !== 'edit'}><RichTextEditor body={draft.body} html={draft.body_html} disabled={readonly} signature={signature} onChange={(body, body_html) => update({ body, body_html })} onError={setError} /></div>
          {viewMode === 'preview' && <div className="compose-preview" aria-label="Email preview" dangerouslySetInnerHTML={{ __html: sanitizeComposeHtml(draft.body_html ?? textToHtml(draft.body)) }} />}
          <div className="compose-attachments"><input ref={fileInput} type="file" multiple hidden aria-label="Attachment files" onChange={event => attach(Array.from(event.target.files || []))} /><button type="button" disabled={readonly} onClick={() => fileInput.current?.click()}><Paperclip size={15} />Attach files</button><span className="mail-muted">Drop files here - Up to 25 MB total</span>{files.map((file, index) => <div key={`${file.name}:${index}`} className="compose-file"><span>{file.name} ({Math.max(1, Math.round(file.size / 1024))} KB)</span><button type="button" disabled={readonly} aria-label={`Remove ${file.name}`} onClick={() => setFiles(items => items.filter((_, position) => position !== index))}><X size={14} /></button></div>)}</div>
        </div>
      </div>
    </form>
    <div className="composer-footer flex items-center justify-between shrink-0"><div>{!isGmailConnected && <a href={getGmailAuthUrl()}>Connect Gmail to send</a>}</div><div className="flex items-center gap-2">
      {canUseDrafts && <button type="button" disabled={busy || isSaving || loadedDraft?.can_edit === false} onClick={() => { void save(); }}>Save to Gmail</button>}
      <button type="button" aria-label="Discard draft" title="Discard draft" disabled={busy || isSaving} onClick={() => { void discard(); }}><Trash2 size={17} /></button>
      <button type="submit" form="email-form" disabled={busy || isSaving || !isGmailConnected || !accountId || loadedDraft?.can_edit === false}><span>{preparingReview ? 'Preparing...' : 'Send email'}</span><Send size={14} /></button>
    </div></div>
    <dialog ref={reviewDialog} aria-labelledby="send-review-title" className="compose-review" onClose={() => setReview(null)}>
      <h2 id="send-review-title">Review before sending</h2>
      {review && <><p>From: {accounts.find(account => account.id === review.accountId)?.email}</p><dl><dt>To</dt><dd>{review.payload.to || '(None)'}</dd>{review.payload.cc && <><dt>Cc</dt><dd>{review.payload.cc}</dd></>}{review.payload.bcc && <><dt>Bcc</dt><dd>{review.payload.bcc}</dd></>}<dt>Subject</dt><dd>{review.payload.subject}</dd><dt>Attachments</dt><dd>{review.filenames.join(', ') || 'None'}</dd></dl><div className="compose-preview" dangerouslySetInnerHTML={{ __html: sanitizeComposeHtml(review.payload.body_html ?? textToHtml(review.payload.body)) }} /><p>You have 10 seconds to undo before Gmail receives the send request. Keep this tab open until sending finishes.</p></>}
      <div className="compose-review-actions"><button type="button" onClick={() => reviewDialog.current?.close()}>Keep editing</button><button type="button" onClick={queueSend}>Confirm send</button></div>
    </dialog>
  </section>;
}
