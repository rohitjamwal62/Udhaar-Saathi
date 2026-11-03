import test from 'node:test';
import assert from 'node:assert/strict';
import { formatPaise, formatQuantity, lineTotal, paiseToInput, parseQuantity, parseRupees } from '../core/money';

test('parseRupees is exact and strict', () => {
  assert.equal(parseRupees('1250'), 125000);
  assert.equal(parseRupees('1250.5'), 125050);
  assert.equal(parseRupees('0.07'), 7);
  assert.equal(parseRupees('1,250.00'), 125000);
  assert.equal(parseRupees('12.345'), null);
  assert.equal(parseRupees('-5'), null);
  assert.equal(parseRupees('abc'), null);
  assert.equal(parseRupees(''), null);
});

test('no floating point drift (0.1 + 0.2 style)', () => {
  assert.equal(parseRupees('0.10')! + parseRupees('0.20')!, parseRupees('0.30'));
});

test('quantity parsing and line totals use integer math', () => {
  assert.equal(parseQuantity('1.5'), 1500);
  assert.equal(parseQuantity('0'), null);
  assert.equal(parseQuantity('2.0005'), null);
  assert.equal(lineTotal(4000, 1500), 6000); // 1.5 kg x Rs 40
  assert.equal(lineTotal(333, 3000), 999);
  assert.equal(lineTotal(1, 500), 1); // 0.5 paise rounds half up
  assert.equal(formatQuantity(1500), '1.5');
  assert.equal(formatQuantity(2000), '2');
});

test('Indian digit grouping', () => {
  assert.equal(formatPaise(0), '₹0');
  assert.equal(formatPaise(99900), '₹999');
  assert.equal(formatPaise(100000), '₹1,000');
  assert.equal(formatPaise(12345600), '₹1,23,456');
  assert.equal(formatPaise(1234567850), '₹1,23,45,678.50');
  assert.equal(formatPaise(-5000), '-₹50');
  assert.equal(formatPaise(5000, { showSign: true }), '+₹50');
});

test('paiseToInput round-trips', () => {
  for (const p of [0, 1, 99, 100, 12345, 1000000]) assert.equal(parseRupees(paiseToInput(p)), p);
});
