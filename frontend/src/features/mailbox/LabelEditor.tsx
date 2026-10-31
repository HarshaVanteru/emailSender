import { useId, useState } from 'react';
import { apiRequest } from '../../shared/api/client';
import type { MailDetail, MailLabel } from './types';

export function LabelEditor({ accountId, message, onChanged }: { accountId: number; message: MailDetail; onChanged: (message: MailDetail) => void }) {
  const labelId = useId();
  const [labels, setLabels] = useState<MailLabel[]>([]);
  const [selected, setSelected] = useState('');
  const [name, setName] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  async function load() {
    try { setLabels(await apiRequest<MailLabel[]>(`accounts/${accountId}/labels`)); }
    catch (reason) { setError(reason instanceof Error ? reason.message : 'Could not load labels.'); }
  }
  async function change(operation: 'add' | 'remove' | 'create' | 'rename' | 'delete') {
    if (operation === 'delete' && !window.confirm('Delete this Gmail label from the mailbox? Its messages will remain in Gmail.')) return;
    setBusy(true); setError('');
    try {
      const path = `accounts/${accountId}`;
      if (operation === 'add' || operation === 'remove') {
        onChanged(await apiRequest<MailDetail>(`${path}/emails/${message.id}/labels`, undefined, 'POST', { [operation]: [selected] }));
      } else {
        setLabels(await apiRequest<MailLabel[]>(`${path}/labels${operation === 'create' ? '' : '/' + encodeURIComponent(selected)}`,
          undefined, operation === 'create' ? 'POST' : operation === 'rename' ? 'PATCH' : 'DELETE', operation === 'delete' ? undefined : { name }));
        setName('');
        if (operation === 'delete') setSelected('');
      }
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'Could not change labels.'); }
    finally { setBusy(false); }
  }
  return <details onToggle={event => { if (event.currentTarget.open) void load(); }}>
    <summary>Manage Gmail labels</summary>
    {error && <p role="alert">{error}</p>}
    <label htmlFor={labelId}>Gmail label</label><select id={labelId} value={selected} onChange={event => setSelected(event.target.value)} disabled={busy}>
      <option value="">Choose a label</option>{labels.filter(label => label.type === 'user').map(label => <option key={label.id} value={label.id}>{label.name}{message.labels.includes(label.id) ? ' (applied)' : ''}</option>)}
    </select>
    <button type="button" disabled={busy || !selected} onClick={() => void change(message.labels.includes(selected) ? 'remove' : 'add')}>{message.labels.includes(selected) ? 'Remove label' : 'Apply label'}</button>
    <label>Label name<input value={name} maxLength={225} onChange={event => setName(event.target.value)} disabled={busy} /></label>
    <button type="button" disabled={busy || !name.trim()} onClick={() => void change('create')}>Create label</button>
    <button type="button" disabled={busy || !selected || !name.trim()} onClick={() => void change('rename')}>Rename label</button>
    <button type="button" disabled={busy || !selected} onClick={() => void change('delete')}>Delete label</button>
  </details>;
}
