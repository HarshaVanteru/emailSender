import assert from 'node:assert/strict';
import { test } from 'node:test';
import { buildApiUrl } from '../src/shared/api/apiUrl.ts';

test('configured API origins never duplicate API or version prefixes', () => {
  for (const base of [
    'http://localhost:8000', 'http://localhost:8000/',
    'http://localhost:8000/api', 'http://localhost:8000/api/',
    'http://localhost:8000/api/v1', ' http://localhost:8000/api/v1/ ',
  ]) {
    assert.equal(buildApiUrl(base, 'auth/google'), 'http://localhost:8000/api/v1/auth/google');
    assert.equal(buildApiUrl(base, '/gmail/profile'), 'http://localhost:8000/api/v1/gmail/profile');
  }
});

test('empty API base uses same-origin hosting and the Vite proxy', () => {
  assert.equal(buildApiUrl('', 'auth/google'), '/api/v1/auth/google');
  assert.equal(buildApiUrl('', 'gmail/send'), '/api/v1/gmail/send');
});

test('deployment path prefixes are preserved', () => {
  assert.equal(buildApiUrl('https://example.com/email/api', 'gmail/profile'),
    'https://example.com/email/api/v1/gmail/profile');
});
