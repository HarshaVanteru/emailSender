import { useEffect, useRef, useState } from 'react';
import { fetchThreadCompose, readFileAsBase64, sendThreadMessage } from './api';
import type { ThreadComposeMode, ThreadComposePreview, ThreadSendResponse } from './types';

const labels: Record<ThreadComposeMode, string> = { reply: 'Reply', reply_all: 'Reply all', forward: 'Forward' };
function syncValidity(target: HTMLInputElement | HTMLTextAreaElement) {
  if (target.matches(':user-invalid')) target.setAttribute('aria-invalid', 'true');
  else target.removeAttribute('aria-invalid');
}

export function ThreadComposer({ accountId, messageId, mode, initialBody, onClose, onSent }: {
  accountId: number; messageId: number; mode: ThreadComposeMode;
  initialBody?: string;
  onClose: () => void; onSent: (result: ThreadSendResponse) => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [context, setContext] = useState<ThreadComposePreview | null>(null);
  const [to, setTo] = useState('');
  const [cc, setCc] = useState('');
  const [body, setBody] = useState('');
  const [attachment, setAttachment] = useState<File | null>(null);
  const [step, setStep] = useState<'edit' | 'review'>('edit');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  useEffect(() => {
    const target = dialog.current;
    target?.showModal();
    let active = true;
    void fetchThreadCompose(accountId, messageId, mode).then(result => {
      if (!active) return;
      setContext(result); setTo(result.to.join(', ')); setCc(result.cc.join(', ')); setBody(initialBody ?? result.body);
    }).catch(reason => { if (active) setError(reason instanceof Error ? reason.message : 'Could not prepare this message.'); });
    return () => { active = false; target?.close(); };
  }, [accountId, messageId, mode, initialBody]);
  const recipients = (value: string) => value.split(',').map(item => item.trim()).filter(Boolean);
  async function confirmSend() {
    if (!context || busy) return;
    setBusy(true); setError('');
    try {
      if (attachment && attachment.size > 5 * 1024 * 1024) throw new Error('Attachments must be 5 MB or smaller.');
      const result = await sendThreadMessage(accountId, messageId, {
        mode, context_hash: context.context_hash, to: recipients(to), cc: recipients(cc), body,
        ...(attachment ? { attachment: { filename: attachment.name,
          content_type: attachment.type || 'application/octet-stream', data: await readFileAsBase64(attachment) } } : {}),
      });
      onSent(result);
      dialog.current?.close();
    } catch (reason) {
      const message = reason instanceof Error ? reason.message : 'Gmail could not confirm sending.';
      setError(/could not confirm|failed to fetch|network/i.test(message) ? `${message} Check Gmail Sent before trying again.` : message);
    } finally { setBusy(false); }
  }
  return <dialog ref={dialog} className="thread-compose-dialog" aria-labelledby="thread-compose-title" onClose={onClose}>
    <div className="thread-compose-header"><h2 id="thread-compose-title">{labels[mode]} in Gmail</h2><p>From your connected account. Review every recipient and attachment before sending.</p></div>
    {error && <p role="alert" className="mail-action-alert">{error}</p>}
    {!context && !error && <p role="status" className="mail-muted">Preparing message…</p>}
    {context && <>
      {step === 'edit' ? <form id="thread-compose-form" onSubmit={event => { event.preventDefault(); setError(''); setStep('review'); }}>
        <label>To<input type="email" multiple required aria-errormessage="thread-to-error" value={to} onBlur={event => syncValidity(event.currentTarget)} onChange={event => { setTo(event.target.value); syncValidity(event.currentTarget); }} placeholder="recipient@example.com" /><span id="thread-to-error" className="thread-field-error">Enter at least one valid email address, separated by commas.</span></label>
        <label>Cc<input type="email" multiple aria-errormessage="thread-cc-error" value={cc} onBlur={event => syncValidity(event.currentTarget)} onChange={event => { setCc(event.target.value); syncValidity(event.currentTarget); }} placeholder="Optional recipients" /><span id="thread-cc-error" className="thread-field-error">Use valid email addresses separated by commas.</span></label>
        <div className="thread-compose-subject"><strong>Subject</strong><span>{context.subject}</span></div>
        <label>Message<textarea required aria-errormessage="thread-body-error" rows={mode === 'forward' ? 12 : 8} value={body} onBlur={event => syncValidity(event.currentTarget)} onChange={event => { setBody(event.target.value); syncValidity(event.currentTarget); }} placeholder="Write your message…" /><span id="thread-body-error" className="thread-field-error">Write a message before reviewing.</span></label>
        <label>Attach a file (optional)<input type="file" accept=".pdf,.doc,.docx,.png,.jpg,.jpeg,.txt" onChange={event => setAttachment(event.target.files?.[0] ?? null)} /></label>
        {attachment && <p className="mail-muted">New attachment: {attachment.name}</p>}
        {mode === 'forward' && context.original_attachments > 0 && <p className="mail-action-alert">The original message has {context.original_attachments} attachment(s). They are not included; attach files you want to send.</p>}
      </form> : <div className="thread-compose-review">
        <h3>Review before sending</h3>
        <p><strong>To:</strong> {to}</p>
        {cc.trim() && <p><strong>Cc:</strong> {cc}</p>}
        <p><strong>Subject:</strong> {context.subject}</p>
        <p><strong>Attachment:</strong> {attachment?.name || 'None'}</p>
        {mode === 'forward' && context.original_attachments > 0 && <p>Original attachments are not included.</p>}
        <div className="thread-compose-review-body">{body}</div>
      </div>}
      <div className="thread-compose-actions">
        <button type="button" className="mail-button" disabled={busy} onClick={() => dialog.current?.close()}>Cancel</button>
        {step === 'edit' ? <button className="mail-primary" type="submit" form="thread-compose-form">Review message</button>
          : <><button type="button" className="mail-button" disabled={busy} onClick={() => setStep('edit')}>Keep editing</button>
            <button type="button" className="mail-primary" disabled={busy} onClick={() => void confirmSend()}>{busy ? 'Sending…' : `Confirm ${labels[mode].toLowerCase()}`}</button></>}
      </div>
    </>}
  </dialog>;
}
