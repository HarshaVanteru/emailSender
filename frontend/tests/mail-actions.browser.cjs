// Mocked browser coverage for explicit Gmail mutations. No real messages change.
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const assert = require('node:assert/strict');

(async () => {
  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  try {
    for (const width of [1440, 390]) {
      const page = await browser.newPage({ viewport: { width, height: 900 } });
      page.setDefaultTimeout(10000);
      let canModify = false, labels = ['INBOX', 'UNREAD'], rejectNext = false, mutations = 0;
      const calls = [];
      const summary = () => ({ id: 1, account_id: 1, thread_id: 1, from_address: 'Alex <alex@example.com>',
        subject: 'Project update', snippet: 'Hello', internal_date: 1791543600000, labels, has_attachments: false });
      const detail = () => ({ ...summary(), to_addresses: [{ name: 'Owner', email: 'owner@example.com' }], cc_addresses: [],
        body_text: 'Hello', body_html: null, attachments: [] });
      await page.route('**/api/v1/**', async route => {
        if (route.request().method() === 'GET' && /\/accounts\/\d+\/send-jobs$/.test(new URL(route.request().url()).pathname)) return route.fulfill({ json: [] });
        const url = new URL(route.request().url()), path = url.pathname, method = route.request().method();
        const headers = { 'access-control-allow-origin': '*' };
        if (method === 'OPTIONS') return route.fulfill({ status: 204, headers: { ...headers,
          'access-control-allow-methods': 'GET, POST, PATCH, DELETE', 'access-control-allow-headers': 'authorization,content-type' } });
        let body, status = 200;
        if (path.endsWith('/gmail/profile')) body = { email: 'owner@example.com', is_connected: true };
        else if (path.endsWith('/accounts')) body = [{ id: 1, email: 'owner@example.com', is_connected: true,
          mailbox_access: true, modify_access: canModify, requires_reauth: false }];
        else if (path.endsWith('/labels') || path.endsWith('/sync-jobs')) body = [];
        else if (path.endsWith('/ai')) body = [];
        else if (path.includes('/ai/')) return route.fulfill({ status: 503, json: { detail: 'AI unavailable in this fixture' } });
        else if (path.endsWith('/emails') && method === 'GET') body = { items: !url.searchParams.get('label') || labels.includes(url.searchParams.get('label')) ? [summary()] : [], next_page_token: null };
        else if (path.endsWith('/threads/1')) body = { id: 1, account_id: 1, subject: 'Project update', items: [detail()], next_page_token: null };
        else if (path.includes('/emails/1') && ['PATCH', 'POST', 'DELETE'].includes(method)) {
          mutations++; calls.push({ method, path, body: route.request().postDataJSON?.() });
          if (rejectNext) { rejectNext = false; status = 409; body = { detail: 'Gmail rejected this change.' }; }
          else {
            if (method === 'PATCH') {
              const change = route.request().postDataJSON();
              const next = new Set(labels);
              if (change.read === true) next.delete('UNREAD');
              if (change.read === false) next.add('UNREAD');
              if (change.starred === true) next.add('STARRED');
              if (change.starred === false) next.delete('STARRED');
              labels = [...next];
            } else if (path.endsWith('/archive')) labels = labels.filter(label => label !== 'INBOX');
            else labels = ['TRASH'];
            body = detail();
          }
        } else throw new Error(`Unexpected API request: ${method} ${path}`);
        await route.fulfill({ status, headers, json: body });
      });
      await page.goto((process.env.APP_URL || 'http://127.0.0.1:4174') + '/#token=test-session');
      await page.getByRole('button', { name: /Project update/ }).click();
      await page.getByRole('button', { name: 'Enable mail actions' }).waitFor();
      assert.equal(await page.getByRole('button', { name: 'Enable mail actions' }).isEnabled(), true);
      assert.equal(await page.getByRole('button', { name: 'Mark read' }).count(), 0);
      assert.equal(mutations, 0);
      canModify = true;
      await page.reload();
      await page.getByRole('button', { name: /Project update/ }).click();
      await page.getByRole('button', { name: 'Mark unread', exact: true }).waitFor();
      assert.equal(mutations, 1);
      assert.deepEqual(calls[0].body, { read: true });
      assert.equal(await page.locator('.mail-row.unread').count(), 0);
      await page.getByRole('button', { name: 'Star', exact: true }).click();
      await page.getByRole('button', { name: 'Unstar', exact: true }).waitFor();
      rejectNext = true;
      await page.getByRole('button', { name: 'Mark unread', exact: true }).click();
      await page.getByRole('alert').filter({ hasText: 'Gmail rejected this change' }).waitFor();
      await page.getByRole('button', { name: 'Mark unread', exact: true }).click();
      await page.getByRole('button', { name: 'Mark read', exact: true }).waitFor();
      // Explicitly marking unread must survive subsequent rendering.
      await page.waitForTimeout(300);
      assert.equal(labels.includes('UNREAD'), true);
      await page.getByRole('button', { name: 'Mark read', exact: true }).click();
      await page.getByRole('button', { name: 'Mark unread', exact: true }).waitFor();
      await page.getByRole('button', { name: 'Archive', exact: true }).click();
      await page.getByRole('heading', { name: 'Nothing here yet' }).waitFor();
      assert.deepEqual(calls.map(call => call.method), ['PATCH', 'PATCH', 'PATCH', 'PATCH', 'PATCH', 'POST']);
      assert.equal(calls[5].path, '/api/v1/emails/1/archive');
      await page.getByRole('navigation', { name: 'Mail folders' }).getByRole('button', { name: 'All mail' }).click();
      await page.getByRole('button', { name: /Project update/ }).click();
      await page.getByRole('button', { name: 'Move to trash', exact: true }).click();
      await page.getByRole('dialog', { name: 'Move this message to Trash?' }).waitFor();
      await page.keyboard.press('Escape');
      assert.equal(calls.length, 6);
      await page.getByRole('button', { name: 'Move to trash', exact: true }).click();
      await page.getByRole('button', { name: 'Cancel', exact: true }).click();
      assert.equal(calls.length, 6);
      await page.getByRole('button', { name: 'Move to trash', exact: true }).click();
      await page.getByRole('button', { name: 'Move to Trash', exact: true }).click();
      await page.waitForFunction(() => !document.querySelector('.message-actions')?.textContent.includes('Move to trash'));
      assert.equal(calls[6].method, 'DELETE');
      assert.equal(calls[6].path, '/api/v1/emails/1');
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
      assert.equal(mutations, 7);
      labels = ['INBOX', 'UNREAD'];
      await page.reload();
      await page.getByRole('checkbox', { name: 'Unread only' }).check();
      await page.getByRole('button', { name: /Project update/ }).click();
      await page.getByRole('button', { name: 'Mark unread', exact: true }).waitFor();
      assert.equal(await page.locator('.mail-row').count(), 0);
      assert.equal(await page.getByRole('region', { name: 'Conversation', exact: true }).count(), 1);
      await page.waitForTimeout(300);
      assert.equal(mutations, 8);
      await page.close();
      console.log(`PASS ${width}px: permission upgrade, read/unread, star, archive, trash confirmation, rejection recovery`);
    }
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
