// Local AI-classification fixtures only; no provider requests.
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const assert = require('node:assert/strict');
(async () => {
  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  try {
    for (const width of [1440, 390]) {
      const page = await browser.newPage({ viewport: { width, height: 900 } });
      let classified = false, socket;
      const errors = [];
      page.on('pageerror', error => errors.push(error.message));
      const base = { account_id: 1, thread_id: 1, from_address: 'Alex <alex@example.com>', snippet: 'Review this message', internal_date: Date.now(), labels: ['INBOX', 'CATEGORY_PERSONAL'], has_attachments: false };
      const reviewed = ['critical', 'high', 'normal', 'low'].map((importance, index) => ({ ...base, id: index + 1, subject: `${importance} priority message`, ai_importance: importance, ai_is_spam: false, ai_category: 'work', ai_reason: 'Importance explanation' }));
      const pending = { ...base, id: 5, subject: 'New incoming message awaiting review' };
      const spam = { ...base, id: 6, subject: 'Spam message', ai_is_spam: true };
      await page.routeWebSocket('**/api/v1/accounts/1/events', ws => { socket = ws; ws.onMessage(() => ws.send(JSON.stringify({ type: 'ready', account_id: 1 }))); });
      await page.route('**/api/v1/**', async route => {
        const url = new URL(route.request().url()); const path = url.pathname;
        let json;
        if (path.endsWith('/gmail/profile')) json = { email: 'owner@example.com', is_connected: true };
        else if (path.endsWith('/accounts')) json = [{ id: 1, email: 'owner@example.com', is_connected: true, mailbox_access: true, requires_reauth: false }];
        else if (path.endsWith('/labels') || path.endsWith('/sync-jobs')) json = [];
        else if (path.endsWith('/mybox-status')) json = { enabled: true, configured: true, pending: classified ? 0 : 1, failed: 0 };
        else if (path.endsWith('/emails') || path.endsWith('/search')) {
          let items = url.searchParams.get('label') === 'MYBOX' ? [...reviewed, ...(classified ? [{ ...pending, ai_is_spam: false, ai_importance: 'high' }] : [])] : [...reviewed, pending, spam];
          const query = url.searchParams.get('q'); if (query) items = items.filter(item => item.subject.includes(query));
          json = { items, next_page_token: null };
        } else throw new Error(`Unexpected API ${path}`);
        await route.fulfill({ json });
      });
      await page.goto((process.env.APP_URL || 'http://127.0.0.1:4174') + '/#token=test-session');
      const folders = page.getByRole('navigation', { name: 'Mail folders', exact: true });
      await folders.getByRole('button', { name: 'Mybox', exact: true }).waitFor();
      assert.deepEqual((await folders.getByRole('button').allTextContents()).slice(0, 2), ['Mybox', 'Inbox']);
      await folders.getByRole('button', { name: 'Mybox', exact: true }).click();
      await page.locator('.mail-row').first().waitFor();
      assert.equal(await page.locator('.mail-row').count(), 4);
      for (const importance of ['critical', 'high', 'normal', 'low']) assert.equal(await page.locator(`.mail-row .mail-importance.${importance}`).count(), 1);
      assert.equal(await page.getByRole('button', { name: /Spam message/ }).count(), 0);
      assert.equal(await page.getByRole('button', { name: /New incoming message awaiting review/ }).count(), 0);
      classified = true; socket.send(JSON.stringify({ type: 'mailbox.updated', account_id: 1, revision: 'classified-1' }));
      await page.getByRole('button', { name: /New incoming message awaiting review/ }).waitFor();
      assert.equal(await page.locator('.mail-row').count(), 5);
      await page.getByLabel('Search mail').fill('high priority');
      await page.getByRole('button', { name: 'Search', exact: true }).click();
      await page.waitForFunction(() => document.querySelectorAll('.mail-row').length === 1);
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
      assert.deepEqual(errors, []);
      await page.close();
      console.log(`PASS ${width}px: Mybox above Inbox, importance colors/labels, spam and pending exclusion, AI completion refresh and search`);
    }
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
