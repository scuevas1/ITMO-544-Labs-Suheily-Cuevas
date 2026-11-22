'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const {
  validateZip, validateDate, periodName,
  rainCategory, snowCategory, selectMeteo, makePeriod
} = require('./app');

test('valid US ZIP and non-US ZIP rejection', () => {
  assert.equal(validateZip('60616'), '60616');
  for (const value of ['', '1234', '123456', 'M5V 3L9', 'SW1A 1AA', 'ABCDE', '<script>']) {
    assert.throws(() => validateZip(value));
  }
});

test('morning and night boundaries', () => {
  assert.equal(periodName(5), null);
  assert.equal(periodName(6), 'morning');
  assert.equal(periodName(11), 'morning');
  assert.equal(periodName(12), null);
  assert.equal(periodName(18), 'night');
  assert.equal(periodName(23), 'night');
});

test('rain threshold', () => {
  assert.equal(rainCategory([0], [0]).value, 'No');
  assert.equal(rainCategory([7.59], [50]).value, 'Mild');
  assert.equal(rainCategory([7.6], [50]).value, 'Heavy');
  assert.equal(rainCategory([], [60]).value, null);
});

test('snow threshold', () => {
  assert.equal(snowCategory([0]).value, 'No');
  assert.equal(snowCategory([4.9]).value, 'Mild');
  assert.equal(snowCategory([5]).value, 'Heavy');
  assert.equal(snowCategory([]).value, null);
});

test('Unix time period selection uses local timezone across DST', () => {
  const hourly = {time: [
    Date.parse('2026-11-01T12:00:00Z') / 1000,
    Date.parse('2026-11-01T23:00:00Z') / 1000
  ]};
  assert.deepEqual(selectMeteo(hourly, '2026-11-01', 'morning', 'America/Chicago'), [0]);
  assert.deepEqual(selectMeteo(hourly, '2026-11-01', 'night', 'America/Chicago'), []);
});

test('invalid calendar date and out-of-window date', () => {
  assert.throws(() => validateDate('2026-02-30', 'America/Chicago'));
  assert.throws(() => validateDate('2020-01-01', 'America/Chicago'));
});

test('missing measured data remains unavailable', () => {
  const period = makePeriod('morning','2026-11-01','America/Chicago',[],null);
  assert.equal(period.uv.value,null);
  assert.ok(period.uv.reason);
});
