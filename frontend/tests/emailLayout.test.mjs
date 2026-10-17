import { readFileSync } from 'node:fs';
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { reflowEmailBody } from '../src/features/compose-email/emailLayout.ts';

// Both delivery and preview must agree on wrapping, including existing drafts.
const fixtures = JSON.parse(readFileSync(
  new URL('../../backend/tests/fixtures/email_layout.json', import.meta.url), 'utf8',
));

for (const fixture of fixtures) {
  test(fixture.name, () => {
    assert.equal(reflowEmailBody(fixture.input), fixture.expected);
    assert.equal(reflowEmailBody(fixture.expected), fixture.expected);
  });
}
