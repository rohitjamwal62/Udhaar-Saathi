import test from 'node:test';
import assert from 'node:assert/strict';
import { compareVersions, decideUpdate } from '../core/appUpdate';

test('compareVersions is numeric', () => {
  assert.ok(compareVersions('1.10.0', '1.9.0') > 0);
  assert.equal(compareVersions('1.0', '1.0.0'), 0);
  assert.ok(compareVersions('1.0.0', '1.0.1') < 0);
});

test('decideUpdate', () => {
  const cfg = { latest_version: '1.2.0', minimum_supported_version: '1.1.0', force_update: false };
  assert.equal(decideUpdate('1.0.0', cfg), 'required'); // below minimum supported
  assert.equal(decideUpdate('1.1.0', cfg), 'optional');
  assert.equal(decideUpdate('1.2.0', cfg), 'none');
  assert.equal(decideUpdate('1.1.0', { ...cfg, force_update: true }), 'required');
});
