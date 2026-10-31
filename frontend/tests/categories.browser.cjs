// Gmail category visibility and Primary-only AI controls; all API requests mocked.
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const assert = require('node:assert/strict');
(async () => {
  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  try {
    for (const width of [1440, 390]) {
      const page = await browser.newPage({ viewport: { width, height: 900 } });
      const categories = ['CATEGORY_PERSONAL', 'CATEGORY_PROMOTIONS', 'CATEGORY_SOCIAL', 'CATEGORY_UPDATES', 'CATEGORY_FORUMS', 'SPAM', 'TRASH'];
      const names = ['Primary', 'Promotions', 'Social', 'Updates', 'Forums', 'Spam', 'Trash'];
      const items = categories.map((category, index) => ({ id: index + 1, account_id: 1, thread_id: index + 1,
        subject: `Message in ${names[index]}`, from_address: 'Sender <sender@example.com>', snippet: 'Example',
        internal_date: Date.now(), labels: [category], has_attachments: false }));
      let aiRequests = 0;
      await page.routeWebSocket('**/api/v1/accounts/1/events', ws => { ws.onMessage(() => ws.send(JSON.stringify({ type: 'ready', account_id: 1 }))); });
      await page.route('**/api/v1/**', async route => {
        if (route.request().method() === 'GET' && /\/accounts\/\d+\/send-jobs$/.test(new URL(route.request().url()).pathname)) return route.fulfill({ json: [] });
        const url = new URL(route.request().url()), path = url.pathname;
        let json;
        if (path.endsWith('/gmail/profile')) json = { email: 'owner@example.com', is_connected: true };
        else if (path.endsWith('/accounts')) json = [{ id: 1, email: 'owner@example.com', is_connected: true, mailbox_access: true, modify_access: false, last_synced_at: '2026-10-29T00:00:00Z', mail_import_complete: true }];
        else if (path.endsWith('/labels') || path.endsWith('/sync-jobs')) json = [];
        else if (path.endsWith('/emails')) {
          const label = url.searchParams.get('label');
          json = { items: items.filter(item => item.labels.includes(label)), next_page_token: null };
        } else if (path.endsWith('/ai')) { aiRequests++; json = []; }
        else if (/\/threads\/\d+$/.test(path)) {
          const id = Number(path.split('/').at(-1));
          const item = items.find(item => item.id === id);
          json = { id, subject: item.subject, account_id: 1, items: [{ ...item, body_text: 'Content', body_html: null, to_addresses: [], cc_addresses: [], attachments: [] }], next_page_token: null };
        } else throw new Error(`Unexpected API request ${path}`);
        await route.fulfill({ json });
      });
      await page.goto((process.env.APP_URL || 'http://127.0.0.1:4174') + '/#token=test-session');
      const folders = page.getByRole('navigation', { name: 'Mail folders' });
      for (const [index, name] of names.entries()) {
        await folders.getByRole('button', { name, exact: true }).click();
        await page.getByRole('heading', { name, exact: true }).waitFor();
        const row = page.getByRole('button', { name: new RegExp(`Message in ${name}`) });
        await row.waitFor();
        assert.equal(await page.locator('.mail-row').count(), 1);
        await row.click();
        await page.locator('.thread-message').waitFor();
        if (index === 0) await page.getByRole('button', { name: 'Open AI chat' }).waitFor();
        else assert.equal(await page.getByRole('button', { name: 'Open AI chat' }).count(), 0);
        await page.getByRole('button', { name: 'Back to messages' }).click();
      }
      assert.equal(aiRequests, 1, 'Only the Primary conversation may load AI history');
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
      await page.close();
      console.log(`PASS ${width}px: Gmail category sections, Spam/Trash, Primary-only AI controls`);
    }
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
