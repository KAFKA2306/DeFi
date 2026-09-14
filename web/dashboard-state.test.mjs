import test from 'node:test';
import assert from 'node:assert/strict';
import {deriveDashboardState} from './dashboard-state.mjs';

const NOW = new Date('2026-09-14T12:00:00Z');

function fixture({latest='2026-09-13', same=false, contractChange=false} = {}) {
  const days = [];
  const aave = [];
  const end = new Date(`${latest}T00:00:00Z`);
  for (let offset = 39; offset >= 0; offset -= 1) {
    const date = new Date(end.valueOf() - offset * 86400000).toISOString().slice(0, 10);
    const n = 40 - offset;
    days.push({date, aave_event_count: 100 + n, aave_liquidation_count: 2, uniswap_swap_count: 200 + n});
    aave.push({date, event_count: 100 + n, event_counts: {supply: 30 + n, withdraw: 20 + n, borrow: 15 + n, repay: 14 + n, liquidation: 2}});
  }
  if (same) {
    days.at(-1).uniswap_swap_count = days.at(-2).uniswap_swap_count;
    aave.at(-1).event_counts = {...aave.at(-2).event_counts};
  }
  const records = days.map((row, index) => ({
    date: row.date,
    from_block: 1000 + index * 10,
    to_block: 1009 + index * 10,
    start_boundary: {block_hash: `0x${'1'.repeat(64)}`, raw_ref: {source_evidence_path: 'raw/objects/a.json', source_sha256: 'a'.repeat(64)}},
    end_boundary: {block_hash: `0x${'2'.repeat(64)}`, raw_ref: {source_evidence_path: 'raw/objects/b.json', source_sha256: 'b'.repeat(64)}},
    aave: {raw_refs: [{source_evidence_path: 'raw/objects/c.json', source_sha256: 'c'.repeat(64)}]},
    uniswap: {raw_refs: [{source_evidence_path: 'raw/objects/d.json', source_sha256: 'd'.repeat(64)}]},
  }));
  const changes = [{valid_from_observed_at: '2026-01-01T00:00:00Z', block_number: 1, fingerprint_sha256: '0'.repeat(64)}];
  if (contractChange) changes.push({valid_from_observed_at: `${latest}T00:00:00Z`, block_number: 1390, fingerprint_sha256: 'f'.repeat(64)});
  return {
    dailyPayload: {records: days},
    aavePayload: {records: aave},
    index: {retrieved_at: `${latest}T23:00:00Z`, coverage: {last_date: latest, day_count: days.length, raw_evidence_count: 100}},
    locators: {record_count: records.length, records},
    contracts: {history: {changes}},
    now: NOW,
  };
}

test('complete day is current, comparable, and limited to 30 saved days', () => {
  const state = deriveDashboardState(fixture());
  assert.equal(state.displayable, true);
  assert.deepEqual(state.status.codes, ['CURRENT']);
  assert.equal(state.latest_date, '2026-09-13');
  assert.equal(state.comparison.length, 6);
  assert.equal(state.history[0].points.length, 30);
  assert.equal(state.evidence.from_block, 1390);
});

test('current UTC day is rejected instead of displayed as complete', () => {
  const state = deriveDashboardState(fixture({latest: '2026-09-14'}));
  assert.equal(state.displayable, false);
  assert.equal(state.status.kind, 'PARTIAL_DAY');
  assert.equal(state.headline, null);
});

test('no-change is explicit and does not invent a stress classification', () => {
  const state = deriveDashboardState(fixture({same: true}));
  assert.equal(state.displayable, true);
  assert.ok(state.status.codes.includes('NO_CHANGE'));
  assert.equal(state.comparison.every((row) => row.previous_delta_pct === 0), true);
});

test('stale canonical data remains visible but cannot look current', () => {
  const state = deriveDashboardState(fixture({latest: '2026-09-10'}));
  assert.equal(state.displayable, true);
  assert.equal(state.status.kind, 'STALE');
  assert.match(state.status.message, /older than expected/);
});

test('missing source alignment fails visible', () => {
  const input = fixture();
  input.locators.records.pop();
  input.locators.record_count -= 1;
  const state = deriveDashboardState(input);
  assert.equal(state.displayable, false);
  assert.equal(state.status.kind, 'UNAVAILABLE');
});

test('contract change never silently compares across identity boundary', () => {
  const state = deriveDashboardState(fixture({contractChange: true}));
  assert.equal(state.displayable, true);
  assert.ok(state.status.codes.includes('CONTRACT_CHANGE'));
  assert.equal(state.comparison, null);
  assert.equal(state.history.every((series) => series.points.length === 1), true);
  assert.equal(state.contract_boundary.date, '2026-09-13');
});
