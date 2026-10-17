// Contextual AI suggestions are mocked; no real model or Gmail send is called.
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const assert = require('node:assert/strict');

(async () => {
  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  try {
    for (const width of [1440, 390]) {
      const page = await browser.newPage({ viewport: { width, height: 900 } });
      page.setDefaultTimeout(10000);
      const stored = [];
      let sends = 0;
      const summary = { id: 1, account_id: 1, thread_id: 1, from_address: 'Alex <alex@example.com>',
        subject: 'Project update', snippet: 'Hello', internal_date: 1791543600000, labels: ['INBOX'], has_attachments: false };
      const detail = { ...summary, to_addresses: [{ name: 'Owner', email: 'owner@example.com' }],
        cc_addresses: [], body_text: 'Please send the notes by Friday.', body_html: null, attachments: [] };
      await page.route('**/api/v1/**', async route => {
        const path = new URL(route.request().url()).pathname, method = route.request().method();
        const headers = { 'access-control-allow-origin': '*' };
        if (method === 'OPTIONS') return route.fulfill({ status: 204, headers: { ...headers,
          'access-control-allow-methods': 'GET, POST', 'access-control-allow-headers': 'authorization,content-type' } });
        let body, status = 200;
        if (path.endsWith('/gmail/profile')) body = { email: 'owner@example.com', is_connected: true };
        else if (path.endsWith('/accounts')) body = [{ id: 1, email: 'owner@example.com', is_connected: true,
          last_synced_at: '2026-10-12T02:45:53', mailbox_access: true, modify_access: false, requires_reauth: false }];
        else if (path.endsWith('/sync-jobs')) body = [];
        else if (path.endsWith('/labels')) body = [];
        else if (path.endsWith('/emails')) body = { items: [summary, { ...summary, id: 2, thread_id: 2, subject: 'Travel plans' }], next_page_token: null };
        else if (path.endsWith('/threads/1')) body = { id: 1, account_id: 1, subject: 'Project update', items: [detail], next_page_token: null };
        else if (path.endsWith('/threads/2')) body = { id: 2, account_id: 1, subject: 'Travel plans', items: [{ ...detail, id: 2, thread_id: 2, subject: 'Travel plans' }], next_page_token: null };
        else if (path.endsWith('/threads/2/ai')) body = [];
        else if (path.endsWith('/threads/1/ai') && method === 'GET') body = stored;
        else if (path.includes('/threads/1/ai/') && method === 'POST') {
          const operation = path.split('/').at(-1);
          const payload = route.request().postDataJSON();
          if (operation === 'rewrite') assert.equal(payload.text, 'Please send notes.');
          const results = {
            summarize: { summary: payload.instruction.includes('Explain this conversation') ? 'Alex wants you to send notes by Friday.' : 'Alex requested notes.', key_points: ['Notes due Friday'] },
            generate_reply: { draft: { to: 'alex@example.com', subject: 'Re: Project update', body: 'I will send the notes.' } },
            rewrite: { rewritten_text: 'Could you send the notes?' },
            extract_actions: { actions: [{ action: 'Send notes', due_date: 'Friday' }] },
            classify: { category: 'work', priority: 'normal', reason: 'Project discussion' },
          };
          body = { id: stored.length + 1, message_id: 1, operation, result: results[operation], created_at: '2026-10-10T05:00:00' };
          stored.unshift(body); status = 201;
        } else if (path.endsWith('/messages/1/compose')) body = { mode: 'reply', to: ['alex@example.com'], cc: [],
          subject: 'Re: Project update', body: '', context_hash: 'a'.repeat(64), original_attachments: 0 };
        else if (path.endsWith('/messages/1/send') || path.endsWith('/gmail/send')) {
          sends++; throw new Error('AI must never send an email');
        } else throw new Error(`Unexpected API request: ${method} ${path}`);
        await route.fulfill({ status, headers, json: body });
      });
      await page.goto((process.env.APP_URL || 'http://127.0.0.1:4174') + '/#token=test-session');
      const header = page.locator('.studio-header');
      await header.getByRole('heading', { name: 'Inbox', exact: true }).waitFor();
      assert.equal(await header.getByRole('button', { name: 'Sync mail', exact: true }).count(), 1);
      await header.getByText(/Last synced/).waitFor();
      assert.equal(await page.locator('.mail-main .mail-toolbar, .mail-main .mail-sync-status').count(), 0);
      await page.getByRole('button', { name: /Project update/ }).click();
      await page.getByRole('button', { name: 'Open AI chat' }).click();
      await page.getByRole('dialog', { name: 'Email conversation chat' }).waitFor();
      await page.getByRole('button', { name: 'Generate summarize' }).click();
      await page.getByText('Alex requested notes.').waitFor();
      await page.getByLabel('Suggest reply').check();
      await page.getByRole('button', { name: 'Generate suggest reply' }).click();
      await page.getByText('I will send the notes.').waitFor();
      assert.equal(sends, 0);
      await page.getByRole('button', { name: 'Use in reply editor' }).click();
      const dialog = page.getByRole('dialog', { name: 'Reply in Gmail' });
      assert.equal(await dialog.getByLabel('Message').inputValue(), 'I will send the notes.');
      await dialog.getByRole('button', { name: 'Review message' }).click();
      assert.equal(sends, 0);
      await dialog.getByRole('button', { name: 'Cancel' }).click();
      await page.getByLabel('Rewrite text').check();
      await page.getByLabel('Text to rewrite').fill('Please send notes.');
      await page.getByRole('button', { name: 'Generate rewrite text' }).click();
      await page.getByText('Could you send the notes?').waitFor();
      await page.getByLabel('Find actions').check();
      await page.getByRole('button', { name: 'Generate find actions' }).click();
      await page.getByText(/Send notes.*Friday/).waitFor();
      await page.getByLabel('Classify').check();
      await page.getByRole('button', { name: 'Generate classify' }).click();
      await page.getByText(/work.*normal priority/).waitFor();
      await page.getByRole('button', { name: 'Close chat', exact: true }).click();
      await page.getByRole('button', { name: 'Open AI chat' }).click();
      await page.getByText('Alex requested notes.').waitFor();
      await page.getByRole('button', { name: 'Expand chat' }).click();
      await page.getByRole('button', { name: 'Collapse chat' }).click();
      await page.keyboard.press('Escape');
      assert.equal(await page.getByRole('button', { name: 'Open AI chat' }).getAttribute('aria-expanded'), 'false');
      await page.getByRole('button', { name: 'Open AI chat' }).click();
      await page.getByRole('button', { name: 'Explain this email', exact: true }).click();
      await page.getByText('Alex wants you to send notes by Friday.').waitFor();
      await page.getByRole('button', { name: 'Close chat', exact: true }).click();
      await page.getByRole('button', { name: /Back to messages/ }).click();
      await page.getByRole('button', { name: /Travel plans/ }).click();
      await page.getByRole('button', { name: 'Open AI chat' }).click();
      assert.equal(await page.getByText('Alex requested notes.').count(), 0);
      await page.getByRole('button', { name: 'Close chat', exact: true }).click();
      await page.getByRole('button', { name: /Back to messages/ }).click();
      await page.getByRole('button', { name: /Project update/ }).click();
      await page.getByRole('button', { name: 'Open AI chat' }).click();
      await page.getByText('Alex wants you to send notes by Friday.').waitFor();
      await page.getByRole('button', { name: 'Write', exact: true }).click();
      await page.getByRole('button', { name: 'Open AI chat' }).click();
      await page.getByRole('dialog', { name: 'Writing copilot' }).waitFor();
      assert.equal(sends, 0);
      assert.equal(stored.length, 6);
      assert.equal(sends, 0);
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
      await page.close();
      console.log(`PASS ${width}px: floating chat, explanation, thread isolation/history, writing copilot, reply handoff, no send`);
    }
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
