// No Gmail calls: verify restoring and completing an existing sync across reload.
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const assert = require('node:assert/strict');
(async () => {
  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  try {
    for (const width of [1440, 390]) {
      const page = await browser.newPage({ viewport: { width, height: 900 } });
      page.setDefaultTimeout(10000);
      let completed = false, listReads = 0, syncPosts = 0, socket;
      await page.routeWebSocket("**/api/v1/accounts/1/events", ws => { socket = ws; ws.onMessage(() => ws.send(JSON.stringify({ type: "ready", account_id: 1 }))); });
      const finished = '2026-10-14T12:00:00Z';
      const job = () => ({ id: 29, kind: 'reconcile', status: completed ? 'succeeded' : 'running', error_code: null, finished_at: completed ? finished : null });
      await page.route('**/api/v1/**', async route => {
        if (route.request().method() === 'GET' && /\/accounts\/\d+\/send-jobs$/.test(new URL(route.request().url()).pathname)) return route.fulfill({ json: [] });
        const path = new URL(route.request().url()).pathname;
        const headers = { 'access-control-allow-origin': '*' };
        if (route.request().method() === 'OPTIONS') return route.fulfill({ status: 204, headers: { ...headers, 'access-control-allow-methods': 'GET, POST', 'access-control-allow-headers': 'authorization,content-type' } });
        let body;
        if (path.endsWith('/gmail/profile')) body = { email: 'owner@example.com', is_connected: true };
        else if (path.endsWith('/accounts')) body = [{ id: 1, email: 'owner@example.com', is_connected: true, mailbox_access: true, modify_access: true, last_synced_at: completed ? finished : null }];
        else if (path.endsWith('/sync-jobs')) body = [job()];
        else if (path.endsWith('/sync-jobs/29')) body = job();
        else if (path.endsWith('/sync')) { syncPosts++; throw new Error('Existing sync must be restored without another POST'); }
        else if (path.endsWith('/labels')) body = [];
        else if (path.endsWith('/emails')) { listReads++; body = { items: [], next_page_token: null }; }
        else throw new Error(`Unexpected request ${path}`);
        await route.fulfill({ headers, json: body });
      });
      await page.goto((process.env.APP_URL || 'http://127.0.0.1:4174') + '/#token=test-session');
      await page.getByRole('progressbar', { name: 'Loading your mailbox' }).waitFor();
      assert.equal(await page.getByRole('button', { name: /Sync mail|Syncing/ }).count(), 0);
      await page.reload();
      await page.getByRole('progressbar', { name: 'Loading your mailbox' }).waitFor();
      const before = listReads;
      completed = true;
      socket.send(JSON.stringify({ type: "mailbox.updated", account_id: 1 }));
      await page.getByRole('progressbar', { name: 'Loading your mailbox' }).waitFor({ state: 'detached' });
      await page.waitForFunction(() => !document.querySelector('.mail-list')?.getAttribute('aria-busy') || document.querySelector('.mail-list')?.getAttribute('aria-busy') === 'false');
      assert(listReads > before, 'Messages must refresh after sync completes');
      assert.equal(await page.getByRole('button', { name: 'Sync mail', exact: true }).count(), 0);
      assert.equal(syncPosts, 0);
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
      await page.close();
      console.log(`PASS ${width}px: restore running sync across reload, automatic completion refresh, no manual controls or submission`);
    }
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
