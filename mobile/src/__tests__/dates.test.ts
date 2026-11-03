import test from 'node:test';
import assert from 'node:assert/strict';
import { customRange, parseDay, rangeFor } from '../core/dates';

test('rangeFor today/yesterday are contiguous day windows', () => {
  const now = new Date(2026, 10, 3, 15, 30);
  const t = rangeFor('today', now);
  const y = rangeFor('yesterday', now);
  assert.equal(y.toIso, new Date(2026, 10, 3).toISOString());
  assert.equal(t.fromIso, y.toIso);
});

test('month and previous month', () => {
  const now = new Date(2026, 10, 3);
  assert.equal(rangeFor('month', now).fromIso, new Date(2026, 10, 1).toISOString());
  assert.equal(rangeFor('prevMonth', now).fromIso, new Date(2026, 9, 1).toISOString());
  assert.equal(rangeFor('prevMonth', now).toIso, new Date(2026, 10, 1).toISOString());
});

test('parseDay / customRange validation', () => {
  assert.equal(parseDay('2026-02-30'), null);
  assert.equal(parseDay('3-11-2026'), null);
  assert.ok(parseDay('2026-11-03'));
  assert.equal(customRange('2026-11-05', '2026-11-03'), null);
  assert.ok(customRange('2026-11-03', '2026-11-03'));
});
