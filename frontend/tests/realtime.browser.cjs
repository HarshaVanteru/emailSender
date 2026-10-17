// Desktop/mobile reply and forward review, with every API request mocked.
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const assert = require('node:assert/strict');

(async () => {
  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  try {
    for (const width of [1440, 390]) {
      const page = await browser.newPage({ viewport: { width, height: 900 } });
      page.setDefaultTimeout(10000);
      let sends = 0;
      let incoming = false;
      let mailReads = 0;
      let threadReads = 0;
      const sockets = [];
      await page.routeWebSocket('**/api/v1/accounts/1/events', ws => {
        sockets.push(ws);
        ws.onMessage(raw => {
          assert.equal(JSON.parse(raw).token, 'test-session');
          ws.send(JSON.stringify({ type: 'ready', account_id: 1, revision: sockets.length }));
        });
      });
      const contextHash = 'a'.repeat(64);
      const summary = { id: 1, account_id: 1, thread_id: 1, from_address: 'Alex <alex@example.com>',
        subject: 'Project update', snippet: 'Hello', internal_date: 1791543600000, labels: ['INBOX'], has_attachments: true };
      const detail = { ...summary, to_addresses: [{ name: 'Owner', email: 'owner@example.com' }],
        cc_addresses: [{ name: 'Bob', email: 'bob@example.com' }], body_text: 'Hello', body_html: null,
        attachments: [{ id: 1, filename: 'original.pdf', mime_type: 'application/pdf', size_bytes: 100 }] };
      await page.route('**/api/v1/**', async route => {
        const url = new URL(route.request().url()), path = url.pathname, method = route.request().method();
        const headers = { 'access-control-allow-origin': '*' };
        if (method === 'OPTIONS') return route.fulfill({ status: 204, headers: { ...headers,
          'access-control-allow-methods': 'GET, POST', 'access-control-allow-headers': 'authorization,content-type' } });
        let body;
        if (path.endsWith('/gmail/profile')) body = { email: 'owner@example.com', is_connected: true };
        else if (path.endsWith('/accounts')) body = [{ id: 1, email: 'owner@example.com', is_connected: true,
          mailbox_access: true, modify_access: false, requires_reauth: false }];
        else if (path.endsWith('/labels') || path.endsWith('/sync-jobs') || path.endsWith('/threads/1/ai')) body = [];
        else if (path.endsWith('/emails')) {
          mailReads++;
          body = { items: incoming ? [{ ...summary, id: 2, thread_id: 2, subject: 'New incoming email' }, summary] : [summary], next_page_token: null };
        }
        else if (path.endsWith('/threads/1')) {
          threadReads++;
          body = { id: 1, account_id: 1, subject: 'Project update', items: [detail], next_page_token: null };
        }
        else if (path.endsWith('/messages/1/compose')) {
          const mode = url.searchParams.get('mode');
          body = { mode, context_hash: contextHash, to: mode === 'forward' ? [] : ['alex@example.com'],
            cc: mode === 'reply_all' ? ['bob@example.com'] : [], subject: mode === 'forward' ? 'Fwd: Project update' : 'Re: Project update',
            body: mode === 'forward' ? '---------- Forwarded message ----------\nHello' : '', original_attachments: 1 };
        } else if (path.endsWith('/messages/1/send')) {
          sends++;
          const payload = route.request().postDataJSON();
          assert.equal(payload.context_hash, contextHash);
          if (payload.mode === 'reply_all') {
            assert.deepEqual(payload.to, ['alex@example.com']);
            assert.deepEqual(payload.cc, ['bob@example.com']);
          } else assert.deepEqual(payload.to, ['new@example.com']);
          body = { message_id: `sent${sends}`, threaded: payload.mode !== 'forward' };
        } else if (path.endsWith('/accounts/1/sync')) body = { id: 4, status: 'queued', error_code: null };
        else if (path.endsWith('/sync-jobs/4')) body = { id: 4, status: 'succeeded', error_code: null };
        else throw new Error(`Unexpected API request: ${method} ${path}`);
        await route.fulfill({ headers, json: body });
      });
      await page.goto((process.env.APP_URL || 'http://127.0.0.1:4174') + '/#token=test-session');
      await page.getByRole('button', { name: /Project update/ }).click();
      await page.getByRole('button', { name: 'Reply all' }).click();
      const reply = page.getByRole('dialog', { name: 'Reply all in Gmail' });
      await reply.getByLabel('To').waitFor();
      assert.equal(await reply.getByLabel('To').inputValue(), 'alex@example.com');
      assert.equal(await reply.getByLabel('Cc').inputValue(), 'bob@example.com');
      await reply.getByLabel('Message').fill('Thanks, everyone.');
      const readsBefore = mailReads;
      const threadBefore = threadReads;
      incoming = true;
      sockets.at(-1).send(JSON.stringify({ type: 'mailbox.updated', account_id: 1, revision: 2 }));
      await page.waitForFunction(() => document.body.textContent.includes('New incoming email'));
      await page.waitForTimeout(100);
      assert.ok(mailReads > readsBefore);
      assert.ok(threadReads > threadBefore);
      assert.equal(await reply.getByLabel('Message').inputValue(), 'Thanks, everyone.');
      assert.equal(await reply.isVisible(), true);
      assert.equal(sends, 0);
      const countBefore = sockets.length;
      sockets.at(-1).close({ code: 1012, reason: 'test restart' });
      for (let attempt = 0; attempt < 30 && sockets.length === countBefore; attempt++) await page.waitForTimeout(100);
      assert.ok(sockets.length > countBefore, 'WebSocket should reconnect');
      assert.equal(await reply.getByLabel('Message').inputValue(), 'Thanks, everyone.');
      await page.close();
      console.log(`PASS ${width}px: incoming mail refresh, thread refresh, authenticated reconnect, unsent reply retained, zero sends`);
    }
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
