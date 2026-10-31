// Mocked Gmail drafts and reviewed sends. Every provider request stays local.
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const assert = require('node:assert/strict');

(async () => {
  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  try {
    for (const width of [1440, 390]) {
      const page = await browser.newPage({ viewport: { width, height: 900 } });
      page.setDefaultTimeout(15000);
      let saves = 0, sends = 0;
      let stored = null;
      const headers = { 'access-control-allow-origin': '*' };
      await page.route('**/api/v1/**', async (route) => {
        if (route.request().method() === 'GET' && /\/accounts\/\d+\/send-jobs$/.test(new URL(route.request().url()).pathname)) return route.fulfill({ json: [] });
        const path = new URL(route.request().url()).pathname;
        const method = route.request().method();
        if (method === 'OPTIONS') return route.fulfill({ status: 204, headers: { ...headers,
          'access-control-allow-methods': 'GET, POST, PUT', 'access-control-allow-headers': 'authorization,content-type' } });
        let body, status = 200;
        if (path.endsWith('/gmail/profile')) body = { email: 'owner@example.com', is_connected: true };
        else if (path.endsWith('/accounts')) body = [{ id: 1, email: 'owner@example.com', is_connected: true, requires_reauth: false, draft_access: true }];
        else if (path.endsWith('/labels')) body = [];
        else if (path.endsWith('/emails')) body = { items: [], next_page_token: null };
        else if (path.endsWith('/accounts/1/drafts') && method === 'GET') body = { items: stored ? [{ id: 'draft1', to: stored.to, subject: stored.subject, snippet: stored.body }] : [], next_page_token: null };
        else if (path.endsWith('/accounts/1/drafts') && method === 'POST') {
          saves++;
          const data = route.request().postDataJSON();
          stored = { id: 'draft1', to: data.to, subject: data.subject, body: data.body,
            body_html: data.body_html, attachments: data.attachments || [], can_edit: true, content_hash: 'a'.repeat(64), cc: '', bcc: '' };
          body = stored; status = 201;
        } else if (path.endsWith('/accounts/1/drafts/draft1') && method === 'GET') body = stored;
        else if (path.endsWith('/accounts/1/drafts/draft1/send-jobs') && method === 'POST') {
          sends++;
          assert.equal(route.request().postDataJSON().content_hash, 'a'.repeat(64));
          body = { id: 'send-job-1', status: 'sent', result: { message_id: 'sent1' } };
        } else if (path.endsWith('/gmail/send')) throw new Error('Saved drafts must send through Gmail drafts.send');
        else throw new Error(`Unexpected API request: ${method} ${path}`);
        await route.fulfill({ status, headers, json: body });
      });
      await page.goto((process.env.APP_URL || 'http://127.0.0.1:4174') + '/#token=test-session');
      await page.getByRole('navigation', { name: 'Workspace', exact: true }).getByRole('button', { name: 'Write', exact: true }).click();
      await page.getByLabel('Autosave', { exact: true }).uncheck();
      await page.getByLabel('To', { exact: true }).fill('receiver@example.com');
      await page.getByLabel('Subject').fill('Project update');
      await page.getByLabel('Message', { exact: true }).fill('Hello from the draft editor.');
      await page.getByRole('button', { name: 'Save to Gmail' }).click();
      await page.getByText('Saved to Gmail Drafts.').waitFor();
      assert.equal(saves, 1);
      await page.getByRole('button', { name: 'Gmail drafts' }).click();
      await page.getByRole('button', { name: /Project update.*receiver@example.com/ }).click();
      await page.getByRole('button', { name: 'Send email' }).click();
      await page.getByRole('dialog', { name: 'Review before sending' }).waitFor();
      assert.equal(sends, 0);
      await page.getByRole('button', { name: 'Keep editing' }).click();
      assert.equal(sends, 0);
      await page.getByRole('button', { name: 'Send email' }).click();
      await page.clock.install();
      await page.getByRole('button', { name: 'Confirm send' }).click();
      await page.clock.runFor(10000);
      await page.getByText('Your email was sent successfully.').waitFor();
      assert.equal(sends, 1);

      // Unsupported originals stay untouched; an explicit copy can be sent.
      stored = { id: 'draft1', to: 'receiver@example.com', cc: '', bcc: '', subject: 'External draft',
        body: 'Text from the external draft.', body_html: null, attachments: [], can_edit: false, content_hash: 'b'.repeat(64) };
      const original = stored;
      await page.getByRole('button', { name: 'Gmail drafts' }).click();
      await page.getByRole('button', { name: /External draft.*receiver@example.com/ }).click();
      assert.equal(await page.getByRole('button', { name: 'Send email' }).isDisabled(), true);
      page.once('dialog', dialog => dialog.dismiss());
      await page.getByRole('button', { name: 'Create editable copy' }).click();
      assert.equal(await page.getByRole('button', { name: 'Send email' }).isDisabled(), true);
      page.once('dialog', dialog => dialog.accept());
      await page.getByRole('button', { name: 'Create editable copy' }).click();
      assert.equal(await page.getByRole('button', { name: 'Send email' }).isEnabled(), true);
      assert.equal(await page.getByLabel('Message', { exact: true }).innerText(), original.body);
      assert.equal(stored, original);
      assert.equal(saves, 1);
      await page.getByRole('button', { name: 'Send email' }).click();
      await page.getByRole('dialog', { name: 'Review before sending' }).waitFor();
      assert.equal(saves, 2);
      assert.equal(sends, 1);
      await page.getByRole('button', { name: 'Confirm send' }).click();
      await page.clock.runFor(10000);
      await page.getByText('Your email was sent successfully.').waitFor();
      assert.equal(sends, 2);
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
      await page.close();
      console.log(`PASS ${width}px: Gmail drafts, reviewed sending, and explicit editable copies`);
    }
  } finally { await browser.close(); }
})().catch((error) => { console.error(error); process.exitCode = 1; });
