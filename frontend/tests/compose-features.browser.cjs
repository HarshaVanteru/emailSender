// Gmail-style compose flows with all provider requests mocked; no live mail.
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const assert = require('node:assert/strict');
(async () => {
  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  try {
    for (const width of [1440, 390]) {
      const page = await browser.newPage({ viewport: { width, height: 900 } });
      page.setDefaultTimeout(12000);
      const errors = [];
      page.on('pageerror', error => errors.push(error.message));
      let stored = null, saves = 0, sends = 0, deletes = 0;
      await page.route('**/api/v1/**', async route => {
        if (route.request().method() === 'GET' && /\/accounts\/\d+\/send-jobs$/.test(new URL(route.request().url()).pathname)) return route.fulfill({ json: [] });
        const path = new URL(route.request().url()).pathname;
        const method = route.request().method();
        let json;
        if (path.endsWith('/gmail/profile')) json = { email: 'owner@example.com', is_connected: true, signature: 'Best regards,\nOwner' };
        else if (path.endsWith('/emails')) json = { items: [], next_page_token: null };
        else if (path.endsWith('/labels') || path.endsWith('/sync-jobs')) json = [];
        else if (path.endsWith('/accounts')) json = [{ id: 1, email: 'owner@example.com', is_connected: true, requires_reauth: false, draft_access: true }];
        else if (path.endsWith('/accounts/1/drafts') && method === 'GET') json = { items: stored ? [{ id: 'draft1', to: stored.to, subject: stored.subject, snippet: stored.body }] : [], next_page_token: null };
        else if ((path.endsWith('/accounts/1/drafts') && method === 'POST') || (path.endsWith('/drafts/draft1') && method === 'PUT')) {
          const data = route.request().postDataJSON();
          if (method === 'PUT') assert.equal(data.content_hash, stored.content_hash);
          saves++;
          stored = { ...data, id: 'draft1', can_edit: true, content_hash: saves.toString(16).padStart(64, '0'),
            attachments: (data.attachments || []).map(file => ({ ...file, size_bytes: Buffer.from(file.data, 'base64').length })) };
          json = stored;
        } else if (path.endsWith('/drafts/draft1') && method === 'GET') json = stored;
        else if (path.endsWith('/drafts/draft1/send-jobs')) {
          assert.equal(route.request().postDataJSON().content_hash, stored.content_hash);
          sends++; assert.ok(route.request().headers()['idempotency-key']); json = { id: 'send-job-1', status: 'sent', result: { message_id: 'sent1' } };
        } else if (path.endsWith('/drafts/draft1') && method === 'DELETE') {
          assert.equal(route.request().postDataJSON().content_hash, stored.content_hash);
          deletes++; stored = null;
          return route.fulfill({ status: 204 });
        } else throw new Error(`Unexpected API request: ${method} ${path}`);
        await route.fulfill({ json });
      });
      await page.goto((process.env.APP_URL || 'http://127.0.0.1:4174') + '/#token=test-session');
      await page.getByRole('navigation', { name: 'Workspace', exact: true }).getByRole('button', { name: 'Write', exact: true }).click();
      await page.getByLabel('To', { exact: true }).fill('first@example.com, second@example.com');
      await page.getByRole('button', { name: 'Cc', exact: true }).click();
      await page.getByLabel('Cc', { exact: true }).fill('copy@example.com');
      await page.getByRole('button', { name: 'Bcc', exact: true }).click();
      await page.getByLabel('Bcc', { exact: true }).fill('private@example.com');
      await page.getByLabel('Subject', { exact: true }).fill('Rich compose test');
      const editor = page.getByRole('textbox', { name: 'Message', exact: true });
      await editor.fill('Hello team'); await editor.press('Control+A');
      await page.getByRole('button', { name: 'Bold', exact: true }).click();
      assert.match(await editor.innerHTML(), /<(b|strong)>/);
      await editor.press('ArrowRight');
      await page.getByRole('button', { name: 'Insert signature' }).click();
      assert.match(await editor.innerText(), /Best regards/);
      page.once('dialog', dialog => dialog.accept('https://example.com/project'));
      await page.getByRole('button', { name: 'Insert link', exact: true }).click();
      assert.equal(await editor.locator('a').count(), 1);
      await page.getByLabel('Inline image file', { exact: true }).setInputFiles({ name: 'pixel.png', mimeType: 'image/png', buffer: Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVQIHWP4z8DwHwAFgAI/ScLbtAAAAABJRU5ErkJggg==', 'base64') });
      await editor.locator('img').waitFor();
      await page.getByLabel('Attachment files', { exact: true }).setInputFiles([
        { name: 'one.txt', mimeType: 'text/plain', buffer: Buffer.from('first') },
        { name: 'two.txt', mimeType: 'text/plain', buffer: Buffer.from('second') },
      ]);
      await page.getByText('Autosaved to Gmail.', { exact: true }).waitFor();
      assert.equal(stored.cc, 'copy@example.com'); assert.equal(stored.bcc, 'private@example.com');
      assert.equal(stored.attachments.length, 2); assert.match(stored.body_html, /data:image\/png;base64/);
      await page.getByRole('button', { name: 'Gmail drafts', exact: true }).click();
      await page.getByRole('button', { name: /Rich compose test.*first@example.com/ }).click();
      await editor.locator('img').waitFor();
      assert.equal(await page.getByLabel('Bcc', { exact: true }).inputValue(), 'private@example.com');
      await page.getByRole('button', { name: 'Send email', exact: true }).click();
      const review = page.getByRole('dialog', { name: 'Review before sending', exact: true });
      await review.waitFor();
      assert.match(await review.innerText(), /private@example.com/);
      assert.match(await review.innerText(), /one.txt, two.txt/);
      assert.equal(sends, 0);
      await review.getByRole('button', { name: 'Confirm send' }).click();
      await page.getByRole('button', { name: 'Undo send', exact: true }).click();
      assert.equal(sends, 0);
      await page.getByText('Send cancelled. Your draft is ready to edit.').waitFor();
      assert.match(await editor.innerText(), /Hello team/);
      await page.clock.install();
      await page.getByRole('button', { name: 'Send email', exact: true }).click();
      await review.getByRole('button', { name: 'Confirm send' }).click();
      await page.clock.runFor(10000);
      await page.getByText('Your email was sent successfully.', { exact: true }).waitFor();
      assert.equal(sends, 1);
      await editor.fill('Unfinished draft to discard');
      await page.clock.runFor(2500);
      await page.getByText('Autosaved to Gmail.', { exact: true }).waitFor();
      page.once('dialog', dialog => dialog.accept());
      await page.getByRole('button', { name: 'Discard draft', exact: true }).click();
      await page.getByText('Fresh page', { exact: true }).waitFor();
      assert.equal(deletes, 1); assert.equal(sends, 1);
      assert.equal(await editor.innerText(), '');
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
      assert.deepEqual(errors, []);
      await page.close();
      console.log(`PASS ${width}px: Cc/Bcc, formatting, signature, link, inline image, multiple attachments, autosave/reopen, reviewed send, undo and discard`);
    }
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
