import { apiUrl } from '../../shared/api/client';
import { getToken } from '../google-login/session';

/** Reconnect with bounded backoff; refresh once on reconnect to recover gaps. */
export function watchMailbox(accountId: number, onUpdate: () => void): () => void {
  let stopped = false;
  let socket: WebSocket | undefined;
  let timer: ReturnType<typeof setTimeout> | undefined;
  let delay = 1000;
  function connect() {
    if (stopped) return;
    const token = getToken();
    if (!token) return;
    const url = new URL(apiUrl(`accounts/${accountId}/events`), window.location.href);
    url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:';
    socket = new WebSocket(url);
    const connection = socket;
    connection.onopen = () => {
      if (!stopped) connection.send(JSON.stringify({ token }));
    };
    connection.onmessage = event => {
      if (stopped) return;
      try {
        const message = JSON.parse(event.data);
        if (message.account_id !== accountId) return;
        if (message.type === 'ready' || message.type === 'mailbox.updated') {
          delay = 1000;
          onUpdate();
        }
      } catch { /* Ignore malformed notifications; HTTP remains authoritative. */ }
    };
    connection.onclose = event => {
      if (!stopped && event.code !== 1008) {
        timer = setTimeout(connect, delay + Math.random() * 500);
        delay = Math.min(delay * 2, 30000);
      }
    };
    connection.onerror = () => connection.close();
  }
  connect();
  return () => {
    stopped = true;
    clearTimeout(timer);
    if (socket) {
      socket.onopen = null;
      socket.onmessage = null;
      socket.onclose = null;
      socket.onerror = null;
      socket.close();
    }
  };
}
