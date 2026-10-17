import { useEffect, useState } from 'react';
import { useThreadChatHistory } from './threadChatContext';
import { FloatingChat } from './FloatingChat';
import { generateContextAiSuggestion, listContextAiSuggestions } from './api';
import type { ContextAiOperation, ContextAiSuggestion } from './types';

const actions: { id: ContextAiOperation; label: string }[] = [
  { id: 'summarize', label: 'Summarize' }, { id: 'generate_reply', label: 'Suggest reply' },
  { id: 'rewrite', label: 'Rewrite text' }, { id: 'extract_actions', label: 'Find actions' },
  { id: 'classify', label: 'Classify' },
];

export function ThreadAiPanel({ accountId, threadId, subject, onUseReply }: {
  accountId: number; threadId: number; subject: string; onUseReply?: (messageId: number, body: string) => void;
}) {
  const [operation, setOperation] = useState<ContextAiOperation>('summarize');
  const [instruction, setInstruction] = useState('');
  const [text, setText] = useState('');
  const [items, setItems] = useState<ContextAiSuggestion[]>([]);
  const { prompts, remember } = useThreadChatHistory();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  useEffect(() => {
    let active = true;
    void listContextAiSuggestions(accountId, threadId).then(result => {
      if (active) {
        setItems(previous => previous.length
          ? [...previous, ...result.filter(item => !previous.some(saved => saved.id === item.id))].slice(0, 20)
          : result);
      }
    }).catch(() => { if (active) setError('Past suggestions could not load. You can still generate a new one.'); });
    return () => { active = false; };
  }, [accountId, threadId]);
  async function generate(action = operation, direction = instruction) {
    if (busy) return;
    setBusy(true); setError('');
    try {
      const result = await generateContextAiSuggestion(accountId, threadId, action, {
        instruction: [
          ...items.slice(0, 2).reverse().map(item => {
            const question = prompts[`${accountId}:${threadId}:${item.id}`];
            return `Previous question: ${question || item.operation}\nPrevious answer (context only): ${JSON.stringify(item.result).slice(0, 300)}`;
          }),
          `Current request: ${direction.trim() || actions.find(item => item.id === action)?.label}`,
        ].join('\n').slice(-2000), ...(action === 'rewrite' ? { text: text.trim() } : {}),
      });
      setItems(previous => [result, ...previous].slice(0, 20));
      remember(`${accountId}:${threadId}:${result.id}`, direction.trim() || actions.find(item => item.id === action)?.label || action);
      setInstruction('');
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'AI could not produce a suggestion.'); }
    finally { setBusy(false); }
  }
  return <FloatingChat title="Email conversation chat"><div className="thread-ai-panel">
    <p className="chat-context"><strong>{subject || '(No subject)'}</strong><br />Using up to eight recent synced messages in this conversation.</p>
    <div className="chat-quick-actions">
      <button disabled={busy} onClick={() => { void generate('summarize', 'Summarize this conversation.'); }}>Summarize</button>
      <button disabled={busy} onClick={() => { void generate('summarize', 'Explain this conversation in plain language, including what the sender wants and any uncertainties.'); }}>Explain this email</button>
      <button disabled={busy} onClick={() => { void generate('extract_actions', 'Extract action items and deadlines.'); }}>Extract action items</button>
      <button disabled={busy} onClick={() => { void generate('generate_reply', 'Draft a reply to this conversation.'); }}>Draft a reply</button>
    </div>
    <p className="mail-muted">Suggestions use recent cached messages. Review every detail before using them; nothing is sent or changed here.</p>
    <form onSubmit={event => { event.preventDefault(); void generate(); }} aria-busy={busy}>
      <fieldset><legend>Choose an action</legend><div className="thread-ai-actions">
        {actions.map(item => <label key={item.id}><input type="radio" name="ai-operation" value={item.id} checked={operation === item.id} onChange={() => setOperation(item.id)} />{item.label}</label>)}
      </div></fieldset>
      {operation === 'rewrite' && <label htmlFor="thread-ai-text">Text to rewrite<textarea id="thread-ai-text" name="text" required maxLength={8000} rows={4} value={text} onChange={event => setText(event.target.value)} placeholder="Paste the part you want rewritten" /></label>}
      <label htmlFor="thread-ai-instruction">Ask about this conversation<input id="thread-ai-instruction" name="instruction" disabled={busy} maxLength={900} value={instruction} onChange={event => setInstruction(event.target.value)} placeholder="For example: what does the sender need from me?" /></label>
      <button type="submit" className="mail-primary" disabled={busy}>{busy ? 'Working…' : `Generate ${actions.find(item => item.id === operation)?.label.toLowerCase()}`}</button>
    </form>
    {error && <p role="alert" className="mail-action-alert">{error}</p>}
    {items.length > 0 && <div className="thread-ai-result">
      <div role="log" aria-label="Email chat history" aria-live="polite">
      {[...items].reverse().map(selected => <article key={selected.id} className="thread-chat-exchange">
        <p className="thread-chat-question">{prompts[`${accountId}:${threadId}:${selected.id}`] || actions.find(item => item.id === selected.operation)?.label}</p>
        <div className="thread-ai-content">
        {selected.result.summary && <p>{selected.result.summary}</p>}
        {selected.result.key_points && selected.result.key_points.length > 0 && <ul>{selected.result.key_points.map((point, index) => <li key={index}>{point}</li>)}</ul>}
        {selected.result.draft && <><p><strong>To:</strong> {selected.result.draft.to || 'Choose a recipient'}</p><p><strong>Subject:</strong> {selected.result.draft.subject}</p><p className="thread-ai-prose">{selected.result.draft.body}</p>
          {selected.message_id && onUseReply && <button type="button" className="mail-button" onClick={() => onUseReply(selected.message_id!, selected.result.draft!.body)}>Use in reply editor</button>}</>}
        {selected.result.rewritten_text && <p className="thread-ai-prose">{selected.result.rewritten_text}</p>}
        {selected.result.actions && <ul>{selected.result.actions.length ? selected.result.actions.map((item, index) => <li key={index}>{item.action}{item.owner ? ` · ${item.owner}` : ''}{item.due_date ? ` · ${item.due_date}` : ''}</li>) : <li>No clear actions found.</li>}</ul>}
        {selected.result.category && <p><strong>{selected.result.category}</strong> · {selected.result.priority} priority. {selected.result.reason}</p>}
        </div>
      </article>)}
      </div>
    </div>}
  </div></FloatingChat>;
}
