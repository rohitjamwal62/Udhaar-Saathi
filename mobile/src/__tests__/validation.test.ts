import assert from 'node:assert/strict';
import { test } from 'node:test';
import { emailProblem, normalizeEmail, normalizeMobile, passwordProblem } from '../features/auth/validation';

test('email: empty and malformed addresses are refused with a clear message', () => {
  assert.match(emailProblem('') ?? '', /Enter your email/);
  assert.match(emailProblem('   ') ?? '', /Enter your email/);
  for (const bad of ['plain', 'a@b', 'a@@b.com', 'a b@c.com', '@c.com', 'a@.com', 'a@c.', 'a@c.c']) {
    assert.match(emailProblem(bad) ?? '', /valid email/, bad);
  }
});

test('email: normal addresses pass, whatever the capitals or surrounding spaces', () => {
  for (const good of ['asha@example.com', '  Asha.Verma@Example.COM ', 'rohit+shop@gmail.com', 'a_b-c@sub.domain.co.in']) {
    assert.equal(emailProblem(good), null, good);
  }
});

test('email: it is lower-cased and trimmed before it is sent to the server', () => {
  assert.equal(normalizeEmail('  Asha.Verma@Example.COM '), 'asha.verma@example.com');
});

test('mobile and password rules are unchanged', () => {
  assert.equal(normalizeMobile('98765 43210'), '+919876543210');
  assert.equal(normalizeMobile('0987'), null);
  assert.equal(passwordProblem('short1'), 'Use at least 8 characters');
  assert.equal(passwordProblem('longenough'), 'Include both letters and numbers');
  assert.equal(passwordProblem('longenough1'), null);
});
