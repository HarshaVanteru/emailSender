// Run against a locally served production build. All API traffic is mocked.
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');

fs.mkdirSync(process.env.SCREENSHOT_DIR || 'artifacts', { recursive: true });

(async () => {
  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  try {
    for (const width of [1440, 390]) {
      const page = await browser.newPage({ viewport: { width, height: 900 } });
      let connected = true;
      let deletes = 0;
      let failRevocation = true;
      let sends = 0;
      await page.route('**/api/v1/**', async (route) => {
        const path = new URL(route.request().url()).pathname;
        const headers = { 'access-control-allow-origin': '*' };
        let status = 200;
        let body;
        if (route.request().method() === 'OPTIONS') {
          return route.fulfill({ status: 204, headers: { ...headers,
            'access-control-allow-methods': 'GET, DELETE, POST',
            'access-control-allow-headers': 'authorization,content-type' } });
        }
        if (path.endsWith('/gmail/profile')) {
          body = { email: 'owner@example.com', name: 'Owner', is_connected: connected };
        } else if (path.endsWith('/accounts')) {
          body = [{ id: 1, email: 'owner@example.com', is_connected: connected, requires_reauth: false }];
        } else if (path.endsWith('/labels')) {
          body = [];
        } else if (path.endsWith('/emails')) {
          body = { items: [], next_page_token: null };
        } else if (path.endsWith('/accounts/1') && route.request().method() === 'DELETE') {
          deletes++;
          if (failRevocation) { status = 502; body = { detail: 'Google could not revoke access. Try again.' }; }
          else { connected = false; body = { status: 'disconnected' }; }
        } else if (path.endsWith('/gmail/send')) {
          sends++;
          throw new Error('The browser test must never send an email');
        } else throw new Error(`Unexpected API request: ${path}`);
        await route.fulfill({ status, headers, json: body });
      });
      await page.goto((process.env.APP_URL || 'http://127.0.0.1:4174') + '/#token=test-session&auth=success');
      await page.getByRole('button', { name: 'Open profile settings' }).waitFor();
      assert.equal(await page.evaluate(() => location.hash), '');
      assert.equal(await page.evaluate(() => localStorage.getItem('access_token')), 'test-session');
      await page.getByRole('navigation', { name: 'Workspace', exact: true }).getByRole('button', { name: 'Write', exact: true }).click();
      assert.equal(await page.getByRole('button', { name: 'Send email', exact: true }).isEnabled(), true);
      await page.getByRole('button', { name: 'Open profile settings' }).click();
      await page.getByRole('button', { name: 'Disconnect Gmail', exact: true }).click();
      await page.getByRole('button', { name: 'Keep connected' }).click();
      assert.equal(deletes, 0);
      await page.getByRole('button', { name: 'Disconnect Gmail', exact: true }).click();
      await page.getByRole('button', { name: 'Confirm disconnect' }).click();
      await page.getByRole('alert').filter({ hasText: 'Google could not revoke' }).waitFor();
      assert.equal(connected, true);
      failRevocation = false;
      await page.getByRole('button', { name: 'Confirm disconnect' }).click();
      await page.getByRole('link', { name: 'Reconnect Gmail', exact: true }).waitFor();
      assert.equal(deletes, 2);
      assert.match(await page.getByRole('link', { name: 'Reconnect Gmail', exact: true }).getAttribute('href'), /renew_consent=true/);
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
      await page.screenshot({ path: `${process.env.SCREENSHOT_DIR || 'artifacts'}/gmail-connection-${width}.png` });
      await page.getByRole('button', { name: 'Close settings' }).click();
      assert.equal(await page.getByRole('button', { name: 'Send email', exact: true }).isDisabled(), true);
      assert.equal(sends, 0);
      // A callback without a refresh token offers renewed consent with the same scope intent.
      for (const flag of ['', 'mailbox_access', 'modify_access', 'draft_access']) {
        await page.goto((process.env.APP_URL || 'http://127.0.0.1:4174') +
          '/#auth=offline_access_required' + (flag ? `&${flag}=true` : ''));
        await page.reload();
        const notice = page.getByRole('status').filter({ hasText: 'Google did not provide ongoing access' });
        const reconnect = notice.getByRole('link', { name: 'Reconnect Gmail', exact: true });
        await reconnect.waitFor();
        const retryUrl = new URL(await reconnect.getAttribute('href'), page.url());
        assert.equal(retryUrl.pathname, '/api/v1/auth/google');
        assert.equal(retryUrl.searchParams.get('renew_consent'), 'true');
        for (const option of ['mailbox_access', 'modify_access', 'draft_access']) {
          assert.equal(retryUrl.searchParams.get(option), option === flag ? 'true' : null);
        }
        assert.equal(await page.evaluate(() => location.hash), '');
        assert.equal(await page.evaluate(() => localStorage.getItem('access_token')), 'test-session');
        assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
      }
      await page.close();
      console.log(`PASS ${width}px: fragment handoff, confirmation, reconnect, offline-access recovery, and disabled send`);
    }
  } finally {
    await browser.close();
  }
})().catch((error) => { console.error(error); process.exitCode = 1; });
