import {deriveDashboardState, formatDelta, METRICS} from './dashboard-state.mjs';

const root = 'api/v1/defi';
const repoRaw = 'https://github.com/KAFKA2306/DeFi/blob/main/data/defi/';
const num = new Intl.NumberFormat('ja-JP');

const esc = (value) => String(value ?? '').replace(/[&<>"']/g, (char) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
const byId = (id) => document.getElementById(id);

function rawLinks(refs, label) {
  if (!Array.isArray(refs) || refs.length === 0) return '<span class="meta">raw refなし</span>';
  return refs.map((ref, index) => `<a href="${repoRaw}${encodeURI(ref.source_evidence_path)}" target="_blank" rel="noreferrer">${esc(label)} ${index + 1} · ${esc(ref.source_sha256.slice(0, 12))}… ↗</a>`).join('');
}

function setUnavailable(state) {
  for (const [, key] of METRICS) byId(key).textContent = '—';
  byId('compare').replaceChildren();
  byId('trends').replaceChildren();
  byId('change-state').textContent = 'Comparable complete-day data is unavailable.';
  byId('asof').textContent = state.status.message;
  byId('block-range').textContent = '—';
  byId('start-hash').textContent = '—';
  byId('end-hash').textContent = '—';
  byId('start-raw').replaceChildren();
  byId('end-raw').replaceChildren();
  byId('aave-raw').replaceChildren();
  byId('uniswap-raw').replaceChildren();
  byId('fingerprint').textContent = '—';
}

function render(state, contracts) {
  const status = byId('status');
  status.dataset.state = state.status.kind;
  status.textContent = `${state.status.codes.join(' + ')} · ${state.status.message}`;

  if (!state.displayable) {
    setUnavailable(state);
    return;
  }

  for (const [, key] of METRICS) byId(key).textContent = num.format(state.headline[key]);
  byId('asof').textContent = `Latest complete UTC day ${state.latest_date} · canonical retrieved ${state.retrieved_at}`;

  if (state.comparison) {
    byId('compare').innerHTML = state.comparison.map((row) => `<article class="card"><div class="label">${esc(row.label)}</div><div class="delta">${formatDelta(row.previous_delta_pct)}</div><div class="note">vs ${state.previous_date}: ${num.format(row.previous)} · vs prior same-contract 7d avg ${row.prior7_average == null ? '—' : formatDelta(row.prior7_delta_pct)}</div></article>`).join('');
  } else {
    byId('compare').innerHTML = '<article class="card"><strong>Comparison unavailable across contract identity boundary</strong><p class="meta">Previous-day and 7-day deltas are intentionally not joined across a contract migration.</p></article>';
  }
  byId('change-state').textContent = state.status.codes.includes('NO_CHANGE') ? 'No verified headline-count change from the previous complete day.' : 'Only same-definition finalized-log deltas are shown; no stress threshold is applied.';

  byId('trends').innerHTML = state.history.map((series) => {
    const max = Math.max(...series.points.map(([, value]) => value), 1);
    const bars = series.points.map(([date, value]) => `<i role="img" aria-label="${esc(date)}: ${num.format(value)}" title="${esc(date)}: ${num.format(value)}" style="height:${Math.max(3, value / max * 100)}%"></i>`).join('');
    const first = series.points.at(0)?.[0] ?? '—';
    const last = series.points.at(-1)?.[0] ?? '—';
    return `<article class="card"><div class="label">${esc(series.label)}</div><div class="trend" aria-label="${esc(series.label)} saved complete-day history">${bars}</div><div class="note">${first} → ${last}</div></article>`;
  }).join('');

  const evidence = state.evidence;
  byId('block-range').textContent = `${state.latest_date} · ${num.format(evidence.from_block)} → ${num.format(evidence.to_block)}`;
  byId('start-hash').textContent = evidence.start_boundary.block_hash;
  byId('end-hash').textContent = evidence.end_boundary.block_hash;
  byId('start-raw').innerHTML = rawLinks([evidence.start_boundary.raw_ref], 'boundary raw');
  byId('end-raw').innerHTML = rawLinks([evidence.end_boundary.raw_ref], 'boundary raw');
  byId('aave-raw').innerHTML = rawLinks(evidence.aave.raw_refs, 'Aave raw');
  byId('uniswap-raw').innerHTML = rawLinks(evidence.uniswap.raw_refs, 'Uniswap raw');

  const latestFingerprint = contracts?.history?.changes?.at(-1);
  byId('fingerprint').textContent = latestFingerprint ? `${latestFingerprint.fingerprint_sha256} · observed block ${num.format(latestFingerprint.block_number)}` : 'No fingerprint history';
  byId('contract-boundary').textContent = state.contract_boundary ? `Identity boundary ${state.contract_boundary.date}; comparisons/history are segmented here.` : 'No contract identity change inside the displayed history segment.';
  byId('why').textContent = `Latest complete day ${state.latest_date}: Borrow ${num.format(state.headline.borrow)}, Repay ${num.format(state.headline.repay)}, LiquidationCall ${num.format(state.headline.liquidation)}, swaps ${num.format(state.headline.swaps)}. These are finalized-log counts, not a solvency or stress score.`;
}

async function load() {
  const paths = ['daily.json', 'aave-daily.json', 'index.json', 'evidence-locators.json', 'contracts.json'];
  try {
    const responses = await Promise.all(paths.map((path) => fetch(`${root}/${path}`, {cache: 'no-store'})));
    if (responses.some((response) => !response.ok)) throw new Error('canonical JSON fetch failed');
    const [dailyPayload, aavePayload, index, locators, contracts] = await Promise.all(responses.map((response) => response.json()));
    render(deriveDashboardState({dailyPayload, aavePayload, index, locators, contracts, now: new Date()}), contracts);
  } catch (error) {
    render({displayable:false,status:{kind:'UNAVAILABLE',codes:['UNAVAILABLE'],message:`Canonical data unavailable: ${error instanceof Error ? error.message : String(error)}`}}, null);
  }
}

load();
