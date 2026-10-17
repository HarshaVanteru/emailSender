// All mail and image responses are fixtures. No real Gmail data or mutations.
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');

const html = `<!doctype html><html><head><style>
  @import url('https://tracker.invalid/stylesheet');
  body { margin:0; padding:0; background:#eef2f6; }
  .newsletter { width:100%; max-width:640px; margin:auto; }
  .hero { padding:36px; background:#183153; color:white; }
  h1 { font-size:32px; margin:0; }
  .content { padding:24px; }
  button { display:none !important; }
  @media(max-width:600px) { .hero { padding:16px; } h1 { font-size:24px; } }
  </style></head><body><table class="newsletter" cellpadding="0" cellspacing="0" role="presentation">
  <tr><td class="hero"><h1>October project update</h1></td></tr>
  <tr><td class="content" bgcolor="#ffffff">
  <p style="color:#345678;font-size:18px">A formatted newsletter, with its original colors and layout.</p>
  <img src="https://tracker.invalid/banner.png" alt="Project banner" style="width:100%;height:160px;object-fit:cover">
  <table width="100%" cellpadding="12"><tr><td bgcolor="#edf4ff">Design approved</td><td bgcolor="#eaf8f0">Development in progress</td></tr></table>
  <p><a href="https://example.com/update">Read the full update</a></p>
  <div style="height:1100px">Long newsletter content</div><p>End of newsletter</p>
  </td></tr></table>
  <script>parent.__email_attack=true</script>
  <meta http-equiv="refresh" content="0;url=https://tracker.invalid/redirect">
  <base href="https://tracker.invalid/"></body></html>`;
const message = { id: 1, account_id: 1, thread_id: 1, from_address: 'Updates <updates@example.com>',
  subject: 'October project update', snippet: 'A formatted newsletter', internal_date: 1791543600000,
  labels: ['INBOX'], has_attachments: false, attachments: [], to_addresses: [], cc_addresses: [],
  body_html: html, body_text: 'Plain-text project update.' };

(async () => {
  fs.mkdirSync('artifacts', { recursive: true });
  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  try {
    for (const width of [1440, 390]) {
      const page = await browser.newPage({ viewport: { width, height: 900 } });
      page.setDefaultTimeout(10000);
      const requests = [], errors = [];
      page.on('pageerror', error => errors.push(error.message));
      await page.route('https://tracker.invalid/**', async route => {
        requests.push(route.request().url());
        assert(route.request().url().endsWith('/banner.png'));
        await route.fulfill({ contentType: 'image/png', body: Buffer.from(
          'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aQ1sAAAAASUVORK5CYII=', 'base64') });
      });
      await page.route('**/api/v1/**', route => {
        assert.equal(route.request().method(), 'GET');
        const path = new URL(route.request().url()).pathname;
        const body = path.endsWith('/gmail/profile') ? { email: 'owner@example.com', is_connected: true }
          : path.endsWith('/accounts') ? [{ id: 1, email: 'owner@example.com', is_connected: true, mailbox_access: true }]
          : path.endsWith('/labels') ? []
          : path.includes('/threads/') ? { id: 1, account_id: 1, subject: message.subject, items: [message], next_page_token: null }
          : { items: [message], next_page_token: null };
        return route.fulfill({ json: body });
      });
      await page.goto((process.env.APP_URL || 'http://127.0.0.1:4174') + '/#token=fixture-session');
      await page.getByRole('button', { name: /October project update/ }).click();
      const frame = page.frameLocator('iframe[title="Formatted email"]');
      await frame.getByRole('heading', { name: message.subject }).waitFor();
      assert.equal(await frame.locator('.hero').evaluate(el => getComputedStyle(el).backgroundColor), 'rgb(24, 49, 83)');
      assert.equal(await frame.locator('.content > p').first().evaluate(el => getComputedStyle(el).color), 'rgb(52, 86, 120)');
      assert.equal(await frame.locator('h1').evaluate(el => getComputedStyle(el).fontSize), width === 390 ? '24px' : '32px');
      assert.equal(await frame.locator('img').getAttribute('src'), null);
      assert.equal(requests.length, 0);
      assert.equal(await page.getByRole('button', { name: 'Back to messages' }).isVisible(), true);
      assert.equal(await frame.locator('script, base, meta[http-equiv="refresh"]').count(), 0);
      assert.equal(await page.evaluate(() => Boolean(window.__email_attack)), false);
      const emailFrame = page.locator('iframe[title="Formatted email"]');
      await page.waitForFunction(() => document.querySelector('.mail-html-frame').getBoundingClientRect().height > 1100);
      await page.screenshot({ path: `artifacts/html-mail-${width}.png` });

      await page.getByRole('button', { name: 'Show images', exact: true }).click();
      await frame.locator('img').waitFor();
      await page.waitForFunction(() => document.querySelector('.mail-html-frame').contentDocument.querySelector('img').naturalWidth === 1);
      assert.equal(requests.length, 1);
      assert.equal(await frame.locator('img').getAttribute('referrerpolicy'), 'no-referrer');
      assert(!((await emailFrame.getAttribute('sandbox')).split(' ').includes('allow-scripts')));
      await page.getByRole('button', { name: 'Hide images', exact: true }).click();
      await page.getByRole('button', { name: 'Show images', exact: true }).waitFor();
      assert.equal(await frame.locator('img').getAttribute('src'), null);
      await page.getByRole('button', { name: 'Show plain text', exact: true }).click();
      await page.getByText(message.body_text, { exact: true }).waitFor();
      assert.equal(await emailFrame.count(), 0);
      await page.getByRole('button', { name: 'Show formatted message', exact: true }).click();
      await frame.getByRole('heading', { name: message.subject }).waitFor();
      await page.getByRole('button', { name: 'Dark mode', exact: true }).click();
      assert.equal(await frame.locator('html').evaluate(el => getComputedStyle(el).colorScheme), 'light');
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
      assert.deepEqual(errors, []);
      console.log(`PASS ${width}px: original HTML/CSS, responsive newsletter, isolated styles, image consent, no scripts or tracking loads, full-height message, text toggle, dark mode`);
      await page.close();
    }
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
