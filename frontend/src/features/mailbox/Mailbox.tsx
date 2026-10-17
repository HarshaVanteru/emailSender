import { useEffect, useRef, useState } from 'react';
import { Inbox, Send, FileText, Search, PenLine, Mail, Paperclip, Star, ChevronDown, Sparkles } from 'lucide-react';
import { fetchConnectedAccounts, getGmailAuthUrl } from '../google-login/api';
import { fetchLabels, fetchMail } from './api';
import { watchMailbox } from '../mail-sync/realtime';
import { fetchRecentSyncJobs, fetchSyncJob } from '../mail-sync/api';
import type { ConnectedAccount } from '../google-login/types';
import type { MailDetail, MailLabel, MailPage, MailSummary } from './types';
import type { SyncJob } from '../mail-sync/types';
import { mailboxRequest } from '../../shared/api/client';
import { ThreadReader } from './ThreadReader';
import './mailbox.css';

export function Mailbox({ signedIn, onCompose }: { signedIn: boolean; onCompose: () => void }) {
  const [accounts, setAccounts] = useState<ConnectedAccount[]>([]);
  const [selected, setSelected] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    if (!signedIn) return;
    const controller = new AbortController();
    void fetchConnectedAccounts(controller.signal).then(result => { if (!controller.signal.aborted) setAccounts(result); })
      .catch(reason => { if (!controller.signal.aborted) setError(reason.message); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [signedIn, retry]);
  const account = accounts.find(item => item.id === selected) || accounts[0];
  if (!signedIn) return <main className="mail-welcome"><div className="welcome-icon"><Inbox size={26} /></div><p className="eyebrow">A LITTLE SPACE FOR YOUR INBOX</p><h1>Your mail. A clearer view.</h1><p>Connect Gmail to browse your conversations and write with a little help.</p><a className="mail-primary" href={getGmailAuthUrl(false, true)}>Connect Gmail for inbox access</a><button className="mail-text-button" onClick={onCompose}>Go to writing workspace</button></main>;
  if (loading) return <main className="mail-state" role="status">Loading your mailboxes…</main>;
  if (error) return <main className="mail-state" role="alert"><p>{error}</p><button className="mail-button" onClick={() => { setLoading(true); setError(''); setRetry(value => value + 1); }}>Retry mailboxes</button></main>;
  if (!account) return <main className="mail-welcome"><h1>No Gmail account connected</h1><a className="mail-primary" href={getGmailAuthUrl(false, true)}>Connect Gmail for inbox access</a></main>;
  return <AccountMailbox onAccountsChange={setAccounts} key={account.id} account={account} accounts={accounts} onAccount={setSelected} onCompose={onCompose} />;
}

function AccountMailbox({ account, accounts, onAccount, onCompose, onAccountsChange }: {
  onAccountsChange: (accounts: ConnectedAccount[]) => void; account: ConnectedAccount; accounts: ConnectedAccount[]; onAccount: (id: number) => void; onCompose: () => void;
}) {
  const [label, setLabel] = useState('INBOX');
  const [myboxStatus, setMyboxStatus] = useState<{ enabled: boolean; configured: boolean; pending: number; failed: number } | null>(null);
  const [unread, setUnread] = useState(false);
  const [importance, setImportance] = useState<MailSummary['ai_importance']>(null);
  const [search, setSearch] = useState('');
  const [query, setQuery] = useState('');
  const [labels, setLabels] = useState<MailLabel[]>([]);
  const [labelError, setLabelError] = useState('');
  const [revision, setRevision] = useState(0);
  const [job, setJob] = useState<SyncJob | null>(null);
  useEffect(() => {
    if (label !== 'MYBOX') return;
    const request = new AbortController();
    void mailboxRequest<{ enabled: boolean; configured: boolean; pending: number; failed: number }>(`accounts/${account.id}/mybox-status`, request.signal).then(result => { if (!request.signal.aborted) setMyboxStatus(result); }).catch(() => { if (!request.signal.aborted) setMyboxStatus(null); });
    return () => request.abort();
  }, [account.id, label, revision]);
  useEffect(() => {
    if (!account.is_connected || !account.mailbox_access) return;
    return watchMailbox(account.id, () => setRevision(value => value + 1));
  }, [account.id, account.is_connected, account.mailbox_access]);
  useEffect(() => {
    const request = new AbortController();
    void fetchLabels(account.id, request.signal).then(result => { if (!request.signal.aborted) { setLabels(result); setLabelError(''); } }).catch(reason => { if (!request.signal.aborted) setLabelError(reason.message); });
    return () => request.abort();
  }, [account.id, revision]);
  useEffect(() => {
    if (!account.is_connected || !account.mailbox_access) return;
    const request = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    async function restoreSync() {
      try {
        const recent = await fetchRecentSyncJobs(account.id, request.signal);
        if (!request.signal.aborted && recent[0]) {
          const latest = recent[0];
          setJob(previous => !previous || latest.id > previous.id || (latest.id === previous.id && previous.status !== 'succeeded' && previous.status !== 'failed') ? latest : previous);
        }
      } catch { /* Retry status on the next interval. */ }
      finally { if (!request.signal.aborted) timer = setTimeout(restoreSync, 15000); }
    }
    void restoreSync();
    return () => { request.abort(); clearTimeout(timer); };
  }, [account.id, account.is_connected, account.mailbox_access]);
  useEffect(() => {
    if (job?.status !== 'succeeded') return;
    const request = new AbortController();
    void fetchConnectedAccounts(request.signal).then(items => {
      if (!request.signal.aborted) { onAccountsChange(items); setRevision(value => value + 1); }
    }).catch(() => { if (!request.signal.aborted) { setRevision(value => value + 1); } });
    return () => request.abort();
  }, [job?.id, job?.status, onAccountsChange]);
  const pending = job?.status === 'queued' || job?.status === 'running';
  const jobId = job?.id;
  useEffect(() => {
    if (!pending || !jobId) return;
    const request = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const next = await fetchSyncJob(account.id, jobId, request.signal);
        if (request.signal.aborted) return;
        setJob(next);
        if (next.status !== 'succeeded' && next.status !== 'failed') timer = setTimeout(poll, 3000);
      } catch {
        if (!request.signal.aborted) timer = setTimeout(poll, 10000);
      }
    };
    timer = setTimeout(poll, 1600);
    return () => { request.abort(); clearTimeout(timer); };
  }, [account.id, jobId, pending]);
  const title = labels.find(item => item.id === label)?.name || ({ MYBOX: 'Mybox', INBOX: 'Inbox', SENT: 'Sent', DRAFT: 'Drafts' }[label]) || (label ? label : 'All mail');
  return <main className="mailbox-layout">
    <aside className="mail-sidebar" aria-label="Mailbox navigation">
      <button className="mail-primary compose-mail" onClick={onCompose}><PenLine size={17} /> Write an email</button>
      <label className="mail-account">Mailbox<select aria-label="Choose mailbox" value={account.id} onChange={event => onAccount(Number(event.target.value))}>{accounts.map(item => <option key={item.id} value={item.id}>{item.email}</option>)}</select></label>
      <nav aria-label="Mail folders">{[
        { id: 'MYBOX', name: 'Mybox', Icon: Sparkles }, { id: 'INBOX', name: 'Inbox', Icon: Inbox }, { id: 'SENT', name: 'Sent', Icon: Send },
        { id: 'DRAFT', name: 'Drafts', Icon: FileText }, { id: '', name: 'All mail', Icon: Mail },
      ].map(({ id, name, Icon }) => <button key={id} className={label === id ? 'selected' : ''} aria-current={label === id ? 'page' : undefined} onClick={() => setLabel(id)}><Icon size={17} />{name}</button>)}</nav>
      <label className="mail-label-filter">Labels<select aria-label="Filter by label" value={['MYBOX', 'INBOX', 'SENT', 'DRAFT', ''].includes(label) ? '' : label} onChange={event => setLabel(event.target.value)}><option value="">Choose a label</option>{labels.filter(item => !['INBOX', 'SENT', 'DRAFT'].includes(item.id)).map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
      {labelError && <p className="mail-muted" role="alert">Labels could not load. <button className="mail-text-button" onClick={() => setRevision(value => value + 1)}>Retry labels</button></p>}
      <div className="mail-sidebar-note"><span className="eyebrow">ROOM TO FOCUS</span><p>Read here. Find the right words in your writing workspace.</p></div>
    </aside>
    <section className="mail-main" aria-label="Mailbox">
      {(!account.is_connected || !account.mailbox_access) && <div className="mail-notice">{!account.is_connected ? 'Reconnect Gmail to update your mailbox.' : 'Allow read access to bring your Gmail messages here.'} <a href={getGmailAuthUrl(account.requires_reauth, true)}>{account.is_connected ? 'Enable inbox access' : 'Reconnect Gmail'}</a></div>}
      {account.is_connected && account.mailbox_access && !account.modify_access && <div className="mail-notice">To mark, star, archive or trash messages, allow Gmail change access. <a href={getGmailAuthUrl(false, false, true)}>Enable mail actions</a></div>}
      {label === 'MYBOX' && <div className="mybox-notice"><strong>Mybox</strong><p>AI-reviewed incoming mail, with suspected spam excluded. Messages awaiting review stay available in Inbox.</p>{myboxStatus && <p role="status">{!myboxStatus.enabled ? 'Automatic AI review is turned off.' : !myboxStatus.configured ? 'Configure the AI provider to start automatic review.' : `${myboxStatus.pending} messages awaiting AI review.`}{myboxStatus.failed > 0 && <> {myboxStatus.failed} reviews could not finish. <button className="mail-text-button" onClick={() => { void mailboxRequest(`accounts/${account.id}/mybox-retry`, undefined, 'POST').then(() => setRevision(value => value + 1)).catch(() => setLabelError('Could not retry AI review. Please try again.')); }}>Retry reviews</button></>}</p>}<div className="mybox-legend" role="group" aria-label="Filter by importance">{(['critical', 'high', 'normal', 'low'] as const).map(level => <button type="button" key={level} className={`mail-importance mybox-filter ${level}`} aria-pressed={importance === level} onClick={() => setImportance(current => current === level ? null : level)}>{level[0].toUpperCase() + level.slice(1)}</button>)}</div></div>}
      <form className="mail-search" role="search" onSubmit={event => { event.preventDefault(); setQuery(search.trim()); }}><Search size={17} aria-hidden="true" /><input aria-label="Search cached mail" placeholder="Search sender, subject, or message…" value={search} maxLength={200} onChange={event => setSearch(event.target.value)} /><button type="submit">Search</button>{query && <button type="button" onClick={() => { setSearch(''); setQuery(''); }}>Clear</button>}</form>
      <div className="mail-filter-bar"><span>{query ? `Results for “${query}” in ${title}` : 'Recent synchronized messages'}</span><label><input type="checkbox" checked={unread} onChange={event => setUnread(event.target.checked)} /> Unread only</label></div>
      {label === 'DRAFT' && <p className="mail-notice">Drafts saved in Gmail appear here for reading. Your writing workspace draft stays separate.</p>}
      <MailResults key={`${label}:${unread}:${query}:${label === 'MYBOX' ? importance : ''}`} revision={revision} accountId={account.id} label={label} importance={label === 'MYBOX' ? importance : null} unread={unread} query={query} editable={Boolean(account.is_connected && account.modify_access)} sendable={Boolean(account.is_connected)} />
    </section>
  </main>;
}

function MailResults({ accountId, label, importance, unread, query, editable, sendable, revision }: { importance: MailSummary['ai_importance']; revision: number; accountId: number; label: string; unread: boolean; query: string; editable: boolean; sendable: boolean }) {
  const [page, setPage] = useState<MailPage<MailSummary> | null>(null);
  const [pagination, setPagination] = useState<{ revision: number; token: string | null }>({ revision, token: null });
  const token = pagination.revision === revision ? pagination.token : null;
  const [selected, setSelected] = useState<MailSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [retry, setRetry] = useState(0);
  const lastButton = useRef<HTMLButtonElement | null>(null);
  const onChanged = (updated: MailDetail) => {
    const matchesFolder = (!label || (label === 'MYBOX' ? updated.ai_is_spam === false && !updated.labels.some(item => ['SPAM', 'TRASH', 'SENT', 'DRAFT'].includes(item)) : updated.labels.includes(label))) && (!importance || updated.ai_importance === importance);
    const matches = matchesFolder && (!unread || updated.labels.includes('UNREAD'));
    setPage(previous => previous && { ...previous, items: previous.items.map(item => item.id === updated.id ? updated : item).filter(item => item.id !== updated.id || matches) });
    setSelected(previous => previous?.id === updated.id ? (matchesFolder ? updated : null) : previous);
  };
  useEffect(() => {
    const controller = new AbortController();
    void fetchMail(accountId, label, unread, query, token, controller.signal, importance).then(result => {
      if (!controller.signal.aborted) setPage(previous => token && previous ? { ...result, items: [...previous.items, ...result.items] } : result);
    }).catch(reason => { if (!controller.signal.aborted) setError(reason.message); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [accountId, label, importance, unread, query, token, retry, revision]);
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const boundary = (days: number) => {
    const date = new Date(today);
    date.setDate(date.getDate() - days);
    return date.getTime();
  };
  const groups = [
    { title: 'Recent', description: 'Past 7 days', since: boundary(6), items: [] as MailSummary[] },
    { title: 'Last week', description: '7?14 days ago', since: boundary(13), items: [] as MailSummary[] },
    { title: 'Last month', description: '14?30 days ago', since: boundary(29), items: [] as MailSummary[] },
    { title: 'Older', description: 'More than 30 days ago', since: -Infinity, items: [] as MailSummary[] },
  ];
  for (const message of [...(page?.items || [])].sort((a, b) => b.internal_date - a.internal_date)) {
    const group = groups.find(item => message.internal_date >= item.since) || groups[groups.length - 1];
    group.items.push(message);
  }
  return <div className="mail-content" data-reading={Boolean(selected)}>
    <section className="mail-list" aria-label="Messages" aria-busy={loading}>
      {page && groups.filter(group => group.title !== 'Older' || group.items.length > 0).map(group => <details key={group.title} className="mail-date-drawer" open>
        <summary title={group.description}><ChevronDown size={15} aria-hidden="true" /><span>{group.title}</span><small aria-label={`${group.items.length} loaded emails`}>{group.items.length}</small></summary>
        {group.items.length === 0 && <p className="mail-date-empty">No loaded emails in this period.</p>}
        {group.items.map(message => <button key={message.id} className={`mail-row ${message.labels.includes('UNREAD') ? 'unread' : ''} ${selected?.id === message.id ? 'active' : ''}`} aria-current={selected?.id === message.id ? 'true' : undefined} onClick={event => { lastButton.current = event.currentTarget; setSelected(message); }}>
        <span className="mail-row-top"><span className="mail-sender">{message.labels.includes('UNREAD') && <span className="unread-dot" aria-label="Unread" />}{message.from_address || 'Unknown sender'}</span><time>{new Date(message.internal_date).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })}</time></span>
        <span className="mail-row-subject">{label === 'MYBOX' && message.ai_importance && <span className={`mail-importance ${message.ai_importance}`} title={message.ai_reason || undefined}>{message.ai_importance === 'normal' ? 'Normal' : message.ai_importance[0].toUpperCase() + message.ai_importance.slice(1)}</span>}{message.subject || '(No subject)'}{message.has_attachments && <Paperclip size={13} aria-label="Has attachments" />}{message.labels.includes('STARRED') && <Star size={13} aria-label="Starred" />}</span><span className="mail-snippet">{message.snippet || 'Open conversation'}</span>
      </button>)}
      </details>)}
      {loading && <p className="mail-state" role="status">Loading messages…</p>}
      {error && <div className="mail-state" role="alert"><p>{error}</p><button className="mail-button" onClick={() => { setLoading(true); setError(''); setRetry(value => value + 1); }}>Retry messages</button></div>}
      {!loading && !error && page?.items.length === 0 && <div className="mail-empty"><Inbox size={32} /><h2>{query || unread || importance ? 'No matching messages' : 'Nothing here yet'}</h2><p>{query || unread || importance ? 'Try another search or clear the importance or unread filter.' : 'Sync your mailbox to bring recent messages into this folder.'}</p></div>}
      {!loading && !error && page?.next_page_token && <button className="mail-button load-more" onClick={() => { setLoading(true); setPagination({ revision, token: page.next_page_token }); }}>Load more mail</button>}
    </section>
    {selected ? <ThreadReader key={selected.thread_id} accountId={accountId} threadId={selected.thread_id} revision={revision} editable={editable} sendable={sendable} onChanged={onChanged} onBack={() => { setSelected(null); requestAnimationFrame(() => lastButton.current?.focus()); }} /> : <div className="reader-placeholder"><div className="reader-art"><Mail size={35} /></div><h2>A moment for your mail.</h2><p>Choose a message to read the conversation.</p><span>External images stay blocked for your privacy.</span></div>}
  </div>;
}
