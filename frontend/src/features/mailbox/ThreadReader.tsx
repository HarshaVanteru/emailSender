import { useCallback, useEffect, useRef, useState } from 'react';
import { Archive, ArrowLeft, CornerUpLeft, Forward, Mail as MailIcon, MailOpen, Paperclip, Star, Trash2, Users } from 'lucide-react';
import { changeMail, fetchThread } from './api';
import { fetchSyncJob, startSync } from '../mail-sync/api';
import type { MailAction } from './api';
import type { MailDetail, ThreadPage } from './types';
import type { ThreadComposeMode, ThreadSendResponse } from '../compose-email/types';
import { MailBody } from './MailBody';
import { ThreadComposer } from '../compose-email/ThreadComposer';
import { ThreadAiPanel } from '../ai-assistant/ThreadAiPanel';

export function ThreadReader({ accountId, threadId, editable, sendable, onChanged, onBack, revision = 0 }: {
  revision?: number; accountId: number; threadId: number; editable: boolean; sendable: boolean; onChanged: (message: MailDetail) => void; onBack: () => void;
}) {
  const [page, setPage] = useState<ThreadPage | null>(null);
  const [pagination, setPagination] = useState<{ revision: number; token: string | null }>({ revision, token: null });
  const token = pagination.revision === revision ? pagination.token : null;
  const setToken = useCallback((token: string | null) => setPagination({ revision, token }), [revision]);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const [retry, setRetry] = useState(0);
  const back = useRef<HTMLButtonElement>(null);
  const dialog = useRef<HTMLDialogElement>(null);
  const [trashId, setTrashId] = useState<number | null>(null);
  const [busyId, setBusyId] = useState<number | null>(null);
  const [actionError, setActionError] = useState('');
  const [notice, setNotice] = useState('');
  const [compose, setCompose] = useState<{ messageId: number; mode: ThreadComposeMode; initialBody?: string } | null>(null);
  const [syncJobId, setSyncJobId] = useState<number | null>(null);
  const [sentThreaded, setSentThreaded] = useState(true);
  const controller = useRef<AbortController | null>(null);
  const reader = useRef<HTMLElement>(null);
  const seenMessages = useRef(new Set<number>());
  const changed = useRef(onChanged);
  useEffect(() => { changed.current = onChanged; }, [onChanged]);
  useEffect(() => {
    if (!editable || !page) return;
    let active = true;
    const observer = new IntersectionObserver(entries => {
      if (document.visibilityState !== 'visible') return;
      for (const entry of entries) {
        if (!entry.isIntersecting) continue;
        const id = Number((entry.target as HTMLElement).dataset.messageId);
        const message = page.items.find(item => item.id === id);
        if (!message?.labels.includes('UNREAD') || seenMessages.current.has(id)) continue;
        seenMessages.current.add(id);
        void changeMail(accountId, id, 'read').then(updated => {
          if (!reader.current) return;
          setPage(previous => previous && { ...previous, items: previous.items.map(item => item.id === id ? updated : item) });
          changed.current(updated);
        }).catch(reason => {
          if (reader.current) setActionError(reason instanceof Error ? reason.message : 'Could not mark this message as read.');
        });
      }
    }, { root: reader.current?.querySelector('.thread-scroll'), threshold: 0 });
    const observe = () => {
      if (!active || document.visibilityState !== 'visible') return;
      observer.disconnect();
      reader.current?.querySelectorAll('[data-message-id]').forEach(element => observer.observe(element));
    };
    observe();
    document.addEventListener('visibilitychange', observe);
    return () => { active = false; observer.disconnect(); document.removeEventListener('visibilitychange', observe); };
  }, [accountId, editable, page]);

  useEffect(() => () => controller.current?.abort(), []);
  async function runAction(messageId: number, action: MailAction) {
    if (busyId !== null) return;
    if (action === 'read' || action === 'unread') seenMessages.current.add(messageId);
    const request = new AbortController(); controller.current = request;
    setBusyId(messageId); setActionError(''); setNotice('');
    try {
      const updated = await changeMail(accountId, messageId, action, request.signal);
      if (request.signal.aborted) return;
      setPage(previous => previous && { ...previous, items: previous.items.map(item => item.id === updated.id ? updated : item) });
      onChanged(updated);
      setNotice(action === 'trash' ? 'Moved to Trash.' : action === 'archive' ? 'Archived.' : 'Message updated in Gmail.');
    } catch (reason) {
      if (!request.signal.aborted) setActionError(reason instanceof Error ? reason.message : 'Gmail could not update this message.');
    } finally { if (!request.signal.aborted) setBusyId(null); }
  }
  useEffect(() => { back.current?.focus(); }, []);
  useEffect(() => {
    if (syncJobId === null) return;
    let active = true;
    let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      try {
        const job = await fetchSyncJob(accountId, syncJobId!);
        if (!active) return;
        if (job.status === 'succeeded') {
          setSyncJobId(null); setPage(null); setToken(null); setRetry(value => value + 1);
          setNotice(sentThreaded ? 'Sent and conversation refreshed.' : 'Sent, but Gmail placed it in a different conversation. Check Sent.');
        } else if (job.status === 'failed') { setSyncJobId(null); setNotice('Sent. Sync mail to refresh this conversation.'); }
        else timer = setTimeout(poll, 3000);
      } catch { if (active) timer = setTimeout(poll, 6000); }
    }
    timer = setTimeout(poll, 1600);
    return () => { active = false; clearTimeout(timer); };
  }, [accountId, syncJobId, sentThreaded, setToken]);
  async function sent(result: ThreadSendResponse) {
    setSentThreaded(result.threaded);
    setNotice(result.threaded ? 'Sent. Refreshing the conversation…' : 'Sent, but Gmail did not confirm the same conversation. Check Sent.');
    try { const job = await startSync(accountId); setSyncJobId(job.id); }
    catch { setNotice(result.threaded ? 'Sent. Sync mail to refresh the conversation.' : 'Sent. Check Sent for the new conversation.'); }
  }
  useEffect(() => {
    const controller = new AbortController();
    void fetchThread(accountId, threadId, token, controller.signal).then(result => {
      if (!controller.signal.aborted) setPage(previous => token && previous ? { ...result, items: [...previous.items, ...result.items] } : result);
    }).catch(reason => { if (!controller.signal.aborted) setError(reason.message); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [accountId, threadId, token, retry, revision]);
  return <section ref={reader} className="thread-reader" aria-label="Conversation">
    <div className="reader-heading">
      <button ref={back} className="mail-text-button" onClick={onBack}><ArrowLeft size={16} /> Back to messages</button>
      <h2>{page?.subject || (loading ? 'Opening conversation…' : 'Conversation')}</h2>
      <p className="mail-muted">Cached conversation · External images are hidden until you choose to show them</p>
      {actionError && <p className="mail-action-alert" role="alert">{actionError}</p>}
      {notice && <p className="mail-action-notice" role="status">{notice}</p>}
    </div>
    <div className="thread-scroll" aria-busy={loading}>
      <ThreadAiPanel subject={page?.subject || 'Conversation'} accountId={accountId} threadId={threadId} onUseReply={sendable ? (messageId, body) => setCompose({ messageId, mode: 'reply', initialBody: body }) : undefined} />
      {page?.items.map(message => <article className="thread-message" data-message-id={message.id} key={message.id}>
        <header className="message-heading">
          <div className="sender-avatar" aria-hidden="true">{(message.from_address || '?').replace(/^["\s]+/, '').slice(0, 1).toUpperCase()}</div>
          <div><h3>{message.from_address || 'Unknown sender'}</h3>
            <p>To: {message.to_addresses.map(person => person.name ? `${person.name} <${person.email}>` : person.email).join(', ') || 'Undisclosed recipients'}</p>
            {message.cc_addresses.length > 0 && <p>Cc: {message.cc_addresses.map(person => person.email).join(', ')}</p>}
            <time dateTime={new Date(message.internal_date).toISOString()}>{new Date(message.internal_date).toLocaleString()}</time>
          </div>
        </header>
        {sendable && !message.labels.includes('DRAFT') && <div className="message-actions" aria-label={`Reply actions for ${message.subject || 'message'}`}>
          <button onClick={() => setCompose({ messageId: message.id, mode: 'reply' })}><CornerUpLeft size={15} />Reply</button>
          <button onClick={() => setCompose({ messageId: message.id, mode: 'reply_all' })}><Users size={15} />Reply all</button>
          <button onClick={() => setCompose({ messageId: message.id, mode: 'forward' })}><Forward size={15} />Forward</button>
        </div>}
        {editable && <div className="message-actions" aria-label={`Actions for ${message.subject || 'message'}`}>
          <button disabled={busyId !== null} onClick={() => { void runAction(message.id, message.labels.includes('UNREAD') ? 'read' : 'unread'); }}>
            {message.labels.includes('UNREAD') ? <MailOpen size={15} /> : <MailIcon size={15} />}{message.labels.includes('UNREAD') ? 'Mark read' : 'Mark unread'}</button>
          <button disabled={busyId !== null} onClick={() => { void runAction(message.id, message.labels.includes('STARRED') ? 'unstar' : 'star'); }}>
            <Star size={15} fill={message.labels.includes('STARRED') ? 'currentColor' : 'none'} />{message.labels.includes('STARRED') ? 'Unstar' : 'Star'}</button>
          {message.labels.includes('INBOX') && <button disabled={busyId !== null} onClick={() => { void runAction(message.id, 'archive'); }}><Archive size={15} />Archive</button>}
          {!message.labels.includes('TRASH') && <button disabled={busyId !== null} onClick={() => { setTrashId(message.id); dialog.current?.showModal(); }}><Trash2 size={15} />Move to trash</button>}
        </div>}
        <MailBody html={message.body_html} text={message.body_text} />
        {message.attachments.length > 0 && <div className="mail-attachments"><p className="mail-muted">Attachments · Preview and download are not available yet</p>
          <ul>{message.attachments.map(file => <li key={file.id}><Paperclip size={14} aria-hidden="true" />{file.filename || 'Unnamed attachment'} <span>{Math.max(1, Math.round(file.size_bytes / 1024))} KB</span></li>)}</ul>
        </div>}
      </article>)}
      {error && <div className="mail-state" role="alert"><p>{error}</p><button className="mail-button" onClick={() => { setLoading(true); setError(''); setRetry(value => value + 1); }}>Retry conversation</button></div>}
      {loading && <p className="mail-state" role="status">Loading conversation…</p>}
      {!loading && !error && page?.items.length === 0 && <p className="mail-state">No messages are cached in this conversation.</p>}
      {!loading && !error && page?.next_page_token && <button className="mail-button load-more" onClick={() => { setLoading(true); setToken(page.next_page_token); }}>Load more messages</button>}
      <p className="reader-footnote">{editable ? 'Messages are marked as read in Gmail when viewed.' : 'Enable mail actions to mark viewed messages as read in Gmail.'}</p>
    </div>
    <dialog ref={dialog} className="mail-confirm" aria-labelledby="trash-title" onClose={() => setTrashId(null)}>
      <h3 id="trash-title">Move this message to Trash?</h3>
      <p>You can restore it later in Gmail.</p>
      <div><button className="mail-button" onClick={() => dialog.current?.close()}>Cancel</button>
        <button className="mail-primary" onClick={() => { const id = trashId; dialog.current?.close(); if (id !== null) void runAction(id, 'trash'); }}>Move to Trash</button></div>
    </dialog>
    {compose && <ThreadComposer key={`${compose.messageId}:${compose.mode}`} accountId={accountId} messageId={compose.messageId} mode={compose.mode} initialBody={compose.initialBody} onClose={() => setCompose(null)} onSent={(result) => { void sent(result); }} />}
  </section>;
}
