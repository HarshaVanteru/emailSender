import { useState } from 'react';
import { apiUrl, getAuthHeaders } from '../../shared/api/client';

export function DownloadAttachment({ accountId, attachment }: { accountId: number; attachment: { id: number; filename: string } }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  async function download() {
    setBusy(true); setError('');
    try {
      const response = await fetch(apiUrl(`accounts/${accountId}/attachments/${attachment.id}`), { headers: getAuthHeaders() });
      if (!response.ok) throw new Error('Attachment could not be downloaded. Refresh and try again.');
      const url = URL.createObjectURL(await response.blob());
      const link = document.createElement('a');
      link.href = url; link.download = Array.from(attachment.filename).map(char =>
        char.charCodeAt(0) < 32 || char === '/' || char === '\\' ? '_' : char).join('') || 'attachment';
      link.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'Download failed.'); }
    finally { setBusy(false); }
  }
  return <><button type="button" disabled={busy} onClick={() => void download()} aria-label={`Download ${attachment.filename}`}>{busy ? 'Downloading...' : 'Download'}</button>{error && <span role="alert">{error}</span>}</>;
}
