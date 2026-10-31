// Mocked socket/API traffic with virtual time; no Gmail calls.
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const assert = require('node:assert/strict');
(async () => {
  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  try {
    for (const width of [1440, 390]) {
      const page = await browser.newPage({ viewport: { width, height: 900 } });
      await page.clock.install();
      let socket, accept = true, jobs = 0, accounts = 0, mail = 0;
      await page.routeWebSocket('**/api/v1/accounts/1/events', ws => {
        socket = ws;
        ws.onMessage(() => { if (accept) ws.send(JSON.stringify({ type: 'ready', account_id: 1 })); });
      });
      await page.route('**/api/v1/**', async route => {
        if (route.request().method() === 'GET' && /\/accounts\/\d+\/send-jobs$/.test(new URL(route.request().url()).pathname)) return route.fulfill({ json: [] });
        const path = new URL(route.request().url()).pathname;
        let json;
        if (path.endsWith('/gmail/profile')) json = { email: 'owner@example.com', is_connected: true };
        else if (path.endsWith('/accounts')) { accounts++; json = [{ id: 1, email: 'owner@example.com', is_connected: true, mailbox_access: true, last_synced_at: '2026-10-29T00:00:00Z' }]; }
        else if (path.endsWith('/sync-jobs')) { jobs++; json = []; }
        else if (path.endsWith('/labels')) json = [];
        else if (path.endsWith('/emails')) { mail++; json = { items: [], next_page_token: null }; }
        else throw new Error(`Unexpected request ${path}`);
        await route.fulfill({ json });
      });
      await page.goto((process.env.APP_URL || 'http://127.0.0.1:4174') + '/#token=test-session');
      await page.getByRole('heading', { name: 'Nothing here yet' }).waitFor();
      await page.waitForTimeout(300);
      const idle = [jobs, accounts, mail];
      await page.clock.fastForward(35000);
      await page.waitForTimeout(100);
      assert.deepEqual([jobs, accounts, mail], idle, 'Healthy idle socket must not poll HTTP');
      socket.send(JSON.stringify({ type: 'heartbeat', account_id: 1 }));
      await page.waitForTimeout(100);
      assert.deepEqual([jobs, accounts, mail], idle, 'Heartbeat must not fetch HTTP');
      socket.send(JSON.stringify({ type: 'mailbox.updated', account_id: 1 }));
      await page.waitForTimeout(200);
      assert.ok(jobs > idle[0] && mail > idle[2], 'Update event refreshes mail');
      accept = false;
      socket.close({ code: 1012, reason: 'test outage' });
      await page.waitForTimeout(100);
      const offline = jobs;
      await page.clock.fastForward(31000);
      await page.waitForTimeout(200);
      assert.ok(jobs > offline, 'Socket outage enables HTTP fallback');
      await page.evaluate(() => { Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'hidden' }); document.dispatchEvent(new Event('visibilitychange')); });
      const hidden = jobs;
      await page.clock.fastForward(31000);
      await page.waitForTimeout(100);
      assert.equal(jobs, hidden, 'Fallback skips hidden tabs');
      await page.evaluate(() => { Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'visible' }); document.dispatchEvent(new Event('visibilitychange')); });
      await page.waitForTimeout(200);
      assert.ok(jobs > hidden, 'Returning to the tab refreshes immediately');
      accept = true;
      socket.send(JSON.stringify({ type: 'ready', account_id: 1 }));
      await page.waitForTimeout(200);
      const restored = jobs;
      await page.clock.fastForward(31000);
      await page.waitForTimeout(100);
      assert.equal(jobs, restored, 'Reconnect stops fallback polling');
      await page.close();
      console.log(`PASS ${width}px: idle silence, event refresh, outage fallback, hidden pause, visibility refresh, reconnect`);
    }
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
