// New architecture flows; every provider/API response is a nonpersonal fixture.
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
      let older = false, historicalRequests = 0, labelWrites = 0, reconciled = false, connected = 0;
      const labels = [{ id: 'Label_1', name: 'Projects', type: 'user' }];
      const message = { id: 1, account_id: 1, thread_id: 1, from_address: 'Sender <sender@example.com>',
        subject: 'Recent fixture message', snippet: 'A safe test message', internal_date: Date.now(),
        labels: ['INBOX', 'CATEGORY_PERSONAL'], has_attachments: true, to_addresses: [], cc_addresses: [],
        body_text: 'Attachment and label fixture.', body_html: null,
        attachments: [{ id: 1, filename: 'document.txt', mime_type: 'text/plain', size_bytes: 12 }] };
      await page.route('https://accounts.google.com/mock**', route => route.fulfill({ contentType: 'text/html', body: '<p>Mock consent destination</p>' }));
      await page.route('**/api/v1/**', async route => {
        const path = new URL(route.request().url()).pathname, method = route.request().method();
        let body;
        if (path.endsWith('/gmail/profile')) body = { email: 'owner@example.com', is_connected: true };
        else if (path.endsWith('/accounts')) body = [{ id: 1, email: 'owner@example.com', is_connected: true, mailbox_access: true, modify_access: true, draft_access: true }];
        else if (path.endsWith('/sync-jobs') || path.endsWith('/threads/1/ai')) body = [];
        else if (path.endsWith('/emails')) body = { items: [message, ...(older ? [{ ...message, id: 2, thread_id: 2, subject: 'Older fixture message', internal_date: 946684800000 }] : [])], next_page_token: null };
        else if (path.endsWith('/threads/1')) body = { id: 1, account_id: 1, subject: message.subject, items: [message], next_page_token: null };
        else if (path.endsWith('/sync/historical')) {
          historicalRequests++;
          assert.deepEqual(route.request().postDataJSON(), { label: 'INBOX' });
          body = { session_id: 'history-fixture', status: 'pending', has_more: true };
        } else if (path.endsWith('/sync/sessions/history-fixture')) {
          older = true; body = { session_id: 'history-fixture', status: 'completed', has_more: false };
        } else if (path.endsWith('/emails/1/labels')) {
          labelWrites++; assert.deepEqual(route.request().postDataJSON(), { add: ['Label_1'] });
          message.labels.push('Label_1'); body = message;
        } else if (path.endsWith('/labels')) {
          if (method === 'POST') labels.push({ id: 'Label_2', name: route.request().postDataJSON().name, type: 'user' });
          body = labels;
        } else if (path.endsWith('/attachments/1')) {
          return route.fulfill({ contentType: 'application/octet-stream', body: 'fixture-file', headers: { 'content-disposition': 'attachment; filename="document.txt"' } });
        } else if (path.endsWith('/send-jobs')) body = [{ id: 'send-fixture', operation: 'compose', status: reconciled ? 'sent' : 'unknown', result: reconciled ? { message_id: 'provider-id' } : null, error_code: null }];
        else if (path.endsWith('/send-jobs/send-fixture/reconcile')) {
          reconciled = true; body = { id: 'send-fixture', operation: 'compose', status: 'sent', result: { message_id: 'provider-id' } };
        } else if (path.endsWith('/accounts/google/connect')) {
          assert.equal(method, 'POST');
          assert.equal(route.request().headers().authorization, 'Bearer test-session');
          connected++; body = { authorization_url: 'https://accounts.google.com/mock' };
        } else throw new Error(`Unexpected fixture request: ${method} ${path}`);
        return route.fulfill({ json: body });
      });
      await page.goto((process.env.APP_URL || 'http://127.0.0.1:4174') + '/#token=test-session');
      await page.getByRole('button', { name: /Recent fixture message/ }).waitFor();
      assert.equal(historicalRequests, 0);
      await page.getByRole('button', { name: 'Load older mail from Gmail' }).click();
      await page.getByRole('button', { name: /Older fixture message/ }).waitFor();
      assert.equal(historicalRequests, 1);
      await page.getByRole('button', { name: /Recent fixture message/ }).click();
      await page.getByText('Manage Gmail labels', { exact: true }).click();
      await page.getByLabel('Gmail label', { exact: true }).selectOption('Label_1');
      await page.getByRole('button', { name: 'Apply label', exact: true }).click();
      await page.getByRole('button', { name: 'Remove label', exact: true }).waitFor();
      assert.equal(labelWrites, 1);
      await page.getByLabel('Label name', { exact: true }).fill('Follow up');
      await page.getByRole('button', { name: 'Create label', exact: true }).click();
      await page.getByLabel('Gmail label', { exact: true }).selectOption('Label_2');
      const downloadEvent = page.waitForEvent('download');
      await page.getByRole('button', { name: 'Download document.txt' }).click();
      assert.equal((await downloadEvent).suggestedFilename(), 'document.txt');
      await page.getByRole('navigation', { name: 'Workspace', exact: true }).getByRole('button', { name: 'Write', exact: true }).click();
      await page.getByText('Recent send status', { exact: true }).click();
      await page.getByText('compose: unknown', { exact: true }).waitFor();
      await page.getByRole('button', { name: 'Check Gmail Sent', exact: true }).click();
      await page.getByText('compose: sent', { exact: true }).waitFor();
      await page.getByRole('button', { name: 'Open profile settings' }).click();
      await page.getByRole('button', { name: 'Add Gmail account', exact: true }).click();
      await page.waitForURL('https://accounts.google.com/mock');
      assert.equal(connected, 1);
      assert.deepEqual(errors, []);
      await page.close();
      console.log(`PASS ${width}px: explicit history, label assignment/creation, on-demand download, unknown-send reconciliation, authenticated add-account`);
    }
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
