import { apiUrl } from '../../shared/api/client';
import { getToken } from '../google-login/session';

/** Events while connected; bounded polling only while the socket is unavailable. */
export function watchMailbox(accountId: number, onUpdate: () => void): () => void {
  let stopped = false;
  let socket: WebSocket | undefined;
  let reconnect: ReturnType<typeof setTimeout> | undefined;
  let fallback: ReturnType<typeof setTimeout> | undefined;
  let watchdog: ReturnType<typeof setTimeout> | undefined;
  let delay = 1000;
  let ready = false;
  function refresh() {
    if (!stopped && document.visibilityState !== 'hidden') onUpdate();
  }
  function startFallback() {
    if (stopped || fallback) return;
    fallback = setTimeout(() => {
      fallback = undefined;
      if (!ready) { refresh(); startFallback(); }
    }, 30000);
  }
  function armWatchdog(connection: WebSocket) {
    clearTimeout(watchdog);
    watchdog = setTimeout(() => connection.close(), 90000);
  }
  function connect() {
    if (stopped) return;
    const token = getToken();
    if (!token) return;
    const url = new URL(apiUrl(`accounts/${accountId}/events`), window.location.href);
    url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:';
    const connection = new WebSocket(url);
    socket = connection;
    armWatchdog(connection);
    connection.onopen = () => {
      if (!stopped) connection.send(JSON.stringify({ token }));
    };
    connection.onmessage = event => {
      if (stopped) return;
      try {
        const message = JSON.parse(event.data);
        if (message.account_id !== accountId) return;
        if (message.type === 'ready' || message.type === 'heartbeat' || message.type === 'mailbox.updated') {
          armWatchdog(connection);
          if (message.type === 'ready') {
            ready = true;
            delay = 1000;
            clearTimeout(fallback); fallback = undefined;
          }
          if (message.type !== 'heartbeat') refresh();
        }
      } catch { /* Ignore malformed notifications. */ }
    };
    connection.onclose = event => {
      ready = false;
      clearTimeout(watchdog);
      if (stopped) return;
      // Fetch access state once on policy rejection; do not retry expired credentials.
      if (event.code === 1008) { clearTimeout(fallback); fallback = undefined; refresh(); return; }
      startFallback();
      reconnect = setTimeout(connect, delay + Math.random() * 500);
      delay = Math.min(delay * 2, 30000);
    };
    connection.onerror = () => connection.close();
  }
  function visible() {
    if (document.visibilityState !== 'hidden') refresh();
  }
  document.addEventListener('visibilitychange', visible);
  refresh();
  startFallback();
  connect();
  return () => {
    stopped = true;
    clearTimeout(reconnect); clearTimeout(fallback); clearTimeout(watchdog);
    document.removeEventListener('visibilitychange', visible);
    if (socket) {
      socket.onopen = null; socket.onmessage = null;
      socket.onclose = null; socket.onerror = null;
      socket.close();
    }
  };
}
