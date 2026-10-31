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
      const contextHash = 'a'.repeat(64);
      const summary = { id: 1, account_id: 1, thread_id: 1, from_address: 'Alex <alex@example.com>',
        subject: 'Project update', snippet: 'Hello', internal_date: 1791543600000, labels: ['INBOX'], has_attachments: true };
      const detail = { ...summary, to_addresses: [{ name: 'Owner', email: 'owner@example.com' }],
        cc_addresses: [{ name: 'Bob', email: 'bob@example.com' }], body_text: 'Hello', body_html: null,
        attachments: [{ id: 1, filename: 'original.pdf', mime_type: 'application/pdf', size_bytes: 100 }] };
      await page.route('**/api/v1/**', async route => {
        if (route.request().method() === 'GET' && /\/accounts\/\d+\/send-jobs$/.test(new URL(route.request().url()).pathname)) return route.fulfill({ json: [] });
        const url = new URL(route.request().url()), path = url.pathname, method = route.request().method();
        const headers = { 'access-control-allow-origin': '*' };
        if (method === 'OPTIONS') return route.fulfill({ status: 204, headers: { ...headers,
          'access-control-allow-methods': 'GET, POST', 'access-control-allow-headers': 'authorization,content-type' } });
        let body;
        if (path.endsWith('/gmail/profile')) body = { email: 'owner@example.com', is_connected: true };
        else if (path.endsWith('/accounts')) body = [{ id: 1, email: 'owner@example.com', is_connected: true,
          mailbox_access: true, modify_access: false, requires_reauth: false }];
        else if (path.endsWith('/labels')) body = [];
        else if (path.endsWith('/sync-jobs')) body = [];
        else if (path.endsWith('/threads/1/ai')) body = [];
        else if (path.endsWith('/emails')) body = { items: [summary], next_page_token: null };
        else if (path.endsWith('/threads/1')) body = { id: 1, account_id: 1, subject: 'Project update', items: [detail], next_page_token: null };
        else if (path.endsWith('/messages/1/compose')) {
          const mode = url.searchParams.get('mode');
          body = { mode, context_hash: contextHash, to: mode === 'forward' ? [] : ['alex@example.com'],
            cc: mode === 'reply_all' ? ['bob@example.com'] : [], subject: mode === 'forward' ? 'Fwd: Project update' : 'Re: Project update',
            body: mode === 'forward' ? '---------- Forwarded message ----------\nHello' : '', original_attachments: 1 };
        } else if (path.endsWith('/messages/1/send-jobs')) {
          sends++;
          const payload = route.request().postDataJSON();
          assert.equal(payload.context_hash, contextHash);
          if (payload.mode === 'reply_all') {
            assert.deepEqual(payload.to, ['alex@example.com']);
            assert.deepEqual(payload.cc, ['bob@example.com']);
          } else assert.deepEqual(payload.to, ['new@example.com']);
          body = { id: 'send-job-' + sends, status: 'sent', result: { message_id: `sent${sends}`, threaded: payload.mode !== 'forward' } };
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
      await reply.getByRole('button', { name: 'Review message' }).click();
      assert.equal(sends, 0);
      await reply.getByRole('button', { name: 'Keep editing' }).click();
      assert.equal(sends, 0);
      await reply.getByRole('button', { name: 'Review message' }).click();
      await reply.getByRole('button', { name: 'Confirm reply all' }).click();
      await page.getByText(/Sent/).first().waitFor();
      assert.equal(sends, 1);
      await page.getByRole('button', { name: 'Forward', exact: true }).click();
      const forward = page.getByRole('dialog', { name: 'Forward in Gmail' });
      await forward.getByText(/not included; attach files/).waitFor();
      await forward.getByLabel('To').fill('new@example.com');
      await forward.getByRole('button', { name: 'Review message' }).click();
      await forward.getByText('Original attachments are not included.').waitFor();
      await forward.getByRole('button', { name: 'Confirm forward' }).click();
      await page.getByText(/Sent/).first().waitFor();
      assert.equal(sends, 2);
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
      await page.close();
      console.log(`PASS ${width}px: reply-all and forward recipients, review, attachment warning, explicit send`);
    }
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
