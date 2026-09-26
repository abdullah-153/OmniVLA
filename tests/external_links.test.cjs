const assert = require('node:assert/strict');
const test = require('node:test');
const { safeExternalUrl } = require('../console-app/external_links');

test('only ordinary external web links reach the desktop shell', () => {
  assert.equal(safeExternalUrl('https://example.com/path?q=1&x=2'), 'https://example.com/path?q=1&x=2');
  assert.equal(safeExternalUrl('http://docs.python.org/'), 'http://docs.python.org/');
  for (const value of [
    'javascript:alert(1)', 'file:///C:/Windows/system.ini', 'mailto:test@example.com',
    'https://user:password@example.com/', 'https://example.com\\@evil.test/',
    ' https://example.com/', 'https://example.com/ ', 'not-a-url',
  ]) assert.equal(safeExternalUrl(value), null, value);
});
