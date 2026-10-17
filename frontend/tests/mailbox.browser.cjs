// Production-build browser checks. All API traffic is mocked; no Gmail calls.
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');

fs.mkdirSync('artifacts', { recursive: true });
const attack = `<p>Hello Harsha,</p><p><strong>The project is ready for review.</strong> Here are the next steps.</p>
  <ul><li>Review the proposal</li><li>Share your feedback on Friday</li></ul>
  <script>window.__email_attack = true</script><img src="https://tracker.invalid/pixel" onerror="window.__email_attack=true">
  <style>@import url('https://tracker.invalid/style'); body{background:#fafafa} .newsletter-copy{color:#123456}</style>
  <div style="background:url(https://tracker.invalid/bg)" onclick="window.__email_attack=true">Safe closing</div>
  <iframe src="https://tracker.invalid/frame"></iframe><svg><image href="https://tracker.invalid/svg" /></svg>
  <form action="https://tracker.invalid/post"><input autofocus onfocus="window.__email_attack=true"></form>
  <a href="javascript:window.__email_attack=true">Unsafe link</a><a href="/api/v1/gmail/send">Relative link</a>
  <a href="https://example.com/review" ping="https://tracker.invalid/ping">Review document</a>
  <p>Thank you,<br>Alex</p>`;
const summary = (id, overrides = {}) => ({ id, account_id: 1, thread_id: id, from_address: 'Alex Morgan <alex@example.com>',
  subject: id === 1 ? 'A fresh start for the project' : 'Friday planning notes', snippet: 'The project is ready for review. Here are the next steps.',
  internal_date: 1791543600000 + id, labels: ['INBOX', 'UNREAD'], has_attachments: id === 1, ...overrides });
const detail = (id) => ({ ...summary(id), to_addresses: [{ name: 'Harsha', email: 'owner@example.com' }], cc_addresses: [],
  body_html: attack, body_text: 'Plain version: The project is ready for review.',
  attachments: [{ id: 1, filename: 'Project proposal.pdf', size_bytes: 48120, mime_type: 'application/pdf' }] });

(async () => {
  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  try {
    for (const width of [1440, 390]) {
      const page = await browser.newPage({ viewport: { width, height: 900 } });
      page.setDefaultTimeout(10000);
      let attackRequests = 0, mutations = 0, failList = false, syncPosts = 0, threadError = false;
      const requested = [];
      const errors = [];
      page.on('pageerror', error => errors.push(error.message));
      await page.route('https://tracker.invalid/**', route => { attackRequests++; return route.abort(); });
      await page.route('**/api/v1/**', async route => {
        const url = new URL(route.request().url()), path = url.pathname;
        requested.push(url);
        const headers = { 'access-control-allow-origin': '*' };
        if (route.request().method() === 'OPTIONS') return route.fulfill({ status: 204, headers: { ...headers, 'access-control-allow-methods': 'GET, POST', 'access-control-allow-headers': 'authorization,content-type' } });
        let body, status = 200;
        if (path.endsWith('/gmail/profile')) body = { email: 'owner@example.com', name: 'Harsha', is_connected: true };
        else if (path.endsWith('/accounts')) body = [
          { id: 1, email: 'owner@example.com', is_connected: true, mailbox_access: true, requires_reauth: false },
          { id: 2, email: 'second@example.com', is_connected: true, mailbox_access: false, requires_reauth: false },
        ];
        else if (path.endsWith('/sync-jobs')) body = [];
        else if (path.endsWith('/labels')) body = [{ id: 'INBOX', name: 'Inbox', type: 'system' }, { id: 'Label_1', name: 'Projects', type: 'user' }];
        else if (path.endsWith('/emails') || path.endsWith('/search')) {
          if (failList) { status = 503; body = { detail: 'Temporary mailbox error' }; }
          else if (url.searchParams.get('account_id') === '2' || url.searchParams.get('q') === 'nothing' || url.searchParams.get('label') === 'DRAFT') body = { items: [], next_page_token: null };
          else body = { items: [url.searchParams.has('page_token') ? summary(2) : summary(1)], next_page_token: url.searchParams.has('page_token') ? null : 'next-mail' };
        } else if (path.includes('/threads/')) {
          if (threadError) { status = 503; body = { detail: 'Temporary conversation error' }; }
          else body = { id: 1, account_id: 1, subject: summary(1).subject, items: [detail(url.searchParams.has('page_token') ? 3 : 1)], next_page_token: url.searchParams.has('page_token') ? null : 'next-thread' };
        } else if (path.endsWith('/sync') && route.request().method() === 'POST') {
          syncPosts++; status = 503; body = { detail: { accepted: true, job_id: 7, error_code: 'queue_unavailable' } };
        } else if (path.endsWith('/sync-jobs/7')) body = { id: 7, status: 'succeeded', error_code: null };
        else { mutations++; throw new Error(`Unexpected API request: ${route.request().method()} ${path}`); }
        await route.fulfill({ status, headers, json: body });
      });
      await page.goto((process.env.APP_URL || 'http://127.0.0.1:4174') + '/#token=test-session');
      await page.getByRole('button', { name: /A fresh start/ }).waitFor();
      await page.getByRole('button', { name: 'Load more mail', exact: true }).click();
      await page.getByRole('button', { name: /Friday planning/ }).waitFor();
      assert(requested.some(url => url.searchParams.get('page_token') === 'next-mail'));
      const row = page.getByRole('button', { name: /A fresh start/ });
      await row.focus(); await page.keyboard.press('Enter');
      const formatted = page.frameLocator('iframe[title="Formatted email"]').first();
      await formatted.locator('strong').waitFor();
      assert.equal(await formatted.locator('script, iframe, svg, form, input, [onclick], [onerror]').count(), 0);
      assert.equal(await formatted.locator('img').getAttribute('src'), null);
      assert.equal(await formatted.locator('a').filter({ hasText: 'Unsafe link' }).getAttribute('href'), null);
      assert.equal(await formatted.locator('a').filter({ hasText: 'Relative link' }).getAttribute('href'), null);
      const safeLink = formatted.getByRole('link', { name: 'Review document' });
      assert.equal(await safeLink.getAttribute('rel'), 'noopener noreferrer');
      assert.equal(await safeLink.getAttribute('target'), '_blank');
      assert.equal(await safeLink.getAttribute('ping'), null);
      assert.equal(await page.evaluate(() => Boolean(window.__email_attack)), false);
      assert.equal(attackRequests, 0);
      await page.getByRole('button', { name: 'Show plain text', exact: true }).click();
      await page.getByText('Plain version: The project is ready for review.').waitFor();
      await page.getByRole('button', { name: 'Show formatted message' }).click();
      await formatted.locator('strong').waitFor();
      await page.getByRole('button', { name: 'Load more messages', exact: true }).click();
      await page.waitForFunction(() => document.querySelectorAll('.thread-message').length === 2);
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
      await page.locator('.thread-scroll').evaluate(element => { element.scrollTop = 0; });
      await page.screenshot({ path: `artifacts/mailbox-${width}.png` });
      await page.getByRole('button', { name: 'Back to messages' }).click();
      await page.waitForFunction(() => document.activeElement?.classList.contains('mail-row'));
      if (width < 900) assert.equal(await row.isVisible(), true);
      threadError = true;
      await row.click(); await page.getByRole('alert').filter({ hasText: 'Temporary conversation error' }).waitFor();
      threadError = false;
      await page.getByRole('button', { name: 'Retry conversation' }).click();
      await formatted.locator('strong').waitFor();
      await page.getByRole('button', { name: 'Back to messages' }).click();
      await page.getByLabel('Unread only').check();
      await page.getByRole('button', { name: /A fresh start/ }).waitFor();
      assert(requested.some(url => url.searchParams.get('unread') === 'true'));
      await page.getByLabel('Search cached mail').fill('nothing');
      await page.getByRole('button', { name: 'Search', exact: true }).click();
      await page.getByRole('heading', { name: 'No matching messages' }).waitFor();
      await page.getByRole('button', { name: 'Clear', exact: true }).click();
      await page.getByRole('navigation', { name: 'Mail folders' }).getByRole('button', { name: 'Drafts', exact: true }).click();
      await page.getByText('Drafts saved in Gmail appear here', { exact: false }).waitFor();
      await page.getByLabel('Unread only').uncheck();
      await page.getByRole('heading', { name: 'Nothing here yet' }).waitFor();
      failList = true;
      await page.getByRole('navigation', { name: 'Mail folders' }).getByRole('button', { name: 'Sent', exact: true }).click();
      await page.getByRole('alert').filter({ hasText: 'Temporary mailbox error' }).waitFor();
      failList = false;
      await page.getByRole('button', { name: 'Retry messages' }).click();
      await page.getByRole('button', { name: /A fresh start/ }).waitFor();
      await page.getByLabel('Filter by label').selectOption('Label_1');
      await page.getByRole('heading', { name: 'Projects', exact: true }).waitFor();
      await page.getByRole('button', { name: 'Sync mail', exact: true }).click();
      await page.getByText('Sync saved. Waiting for the sync service to recover.').waitFor();
      await page.getByText('Mailbox updated.', { exact: true }).waitFor();
      assert.equal(syncPosts, 1);
      await page.getByLabel('Choose mailbox', { exact: true }).selectOption('2');
      await page.getByRole('link', { name: 'Enable inbox access' }).waitFor();
      assert.match(await page.getByRole('link', { name: 'Enable inbox access' }).getAttribute('href'), /mailbox_access=true/);
      assert.equal(await page.getByRole('button', { name: 'Sync mail', exact: true }).isDisabled(), true);
      await page.getByRole('heading', { name: 'Nothing here yet' }).waitFor();
      assert.equal(await page.getByRole('button', { name: /A fresh start/ }).count(), 0);
      await page.getByRole('navigation', { name: 'Workspace', exact: true }).getByRole('button', { name: 'Write', exact: true }).click();
      await page.getByRole('button', { name: 'Send email', exact: true }).waitFor();
      assert.equal(mutations, 0);
      assert.deepEqual(errors, []);
      console.log(`PASS ${width}px: inbox/thread paging, keyboard focus, isolated HTML, search, filters, errors, account isolation, sync recovery, composer`);
      await page.close();
    }
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
