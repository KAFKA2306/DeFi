export const METRICS = [
  ["Supply", "supply"],
  ["Withdraw", "withdraw"],
  ["Borrow", "borrow"],
  ["Repay", "repay"],
  ["LiquidationCall", "liquidation"],
  ["Uniswap swaps", "swaps"],
];

const DAY_MS = 86_400_000;

function dayString(value) {
  if (typeof value !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(value)) {
    throw new Error(`invalid UTC day: ${value}`);
  }
  const parsed = new Date(`${value}T00:00:00Z`);
  if (Number.isNaN(parsed.valueOf()) || parsed.toISOString().slice(0, 10) !== value) {
    throw new Error(`invalid UTC day: ${value}`);
  }
  return value;
}

function utcDay(date) {
  return new Date(Date.UTC(date.getUTCFullYear(), date.getUTCMonth(), date.getUTCDate()));
}

function shiftDay(day, offset) {
  const value = new Date(`${day}T00:00:00Z`);
  value.setUTCDate(value.getUTCDate() + offset);
  return value.toISOString().slice(0, 10);
}

function metricsFrom(aave, daily) {
  const counts = aave?.event_counts;
  if (!counts || typeof counts !== "object") throw new Error("missing Aave event_counts");
  const values = {
    supply: counts.supply,
    withdraw: counts.withdraw,
    borrow: counts.borrow,
    repay: counts.repay,
    liquidation: counts.liquidation,
    swaps: daily?.uniswap_swap_count,
  };
  for (const [, key] of METRICS) {
    if (!Number.isFinite(values[key]) || values[key] < 0) {
      throw new Error(`invalid metric ${key}`);
    }
  }
  return values;
}

function percent(current, baseline) {
  if (baseline === 0) return current === 0 ? 0 : null;
  return (current / baseline - 1) * 100;
}

function mean(values) {
  return values.length ? values.reduce((sum, value) => sum + value, 0) / values.length : null;
}

function contractBoundary(contracts) {
  const changes = contracts?.history?.changes;
  if (!Array.isArray(changes) || changes.length < 2) return null;
  const latest = changes.at(-1);
  const observed = latest?.valid_from_observed_at;
  if (typeof observed !== "string") throw new Error("contract change is missing valid_from_observed_at");
  const parsed = new Date(observed);
  if (Number.isNaN(parsed.valueOf())) throw new Error("invalid contract change timestamp");
  return {
    date: parsed.toISOString().slice(0, 10),
    block_number: latest.block_number,
    fingerprint_sha256: latest.fingerprint_sha256,
  };
}

function unavailable(reason, code = "UNAVAILABLE") {
  return {
    displayable: false,
    status: {kind: code, codes: [code], message: reason},
    headline: null,
    comparison: null,
    history: null,
    evidence: null,
  };
}

export function deriveDashboardState(input) {
  const {dailyPayload, aavePayload, index, locators, contracts} = input;
  const now = input.now instanceof Date ? input.now : new Date(input.now ?? Date.now());
  if (Number.isNaN(now.valueOf())) return unavailable("Invalid runtime clock");

  try {
    const daily = [...(dailyPayload?.records ?? [])].sort((a, b) => dayString(a.date).localeCompare(dayString(b.date)));
    const aave = [...(aavePayload?.records ?? [])].sort((a, b) => dayString(a.date).localeCompare(dayString(b.date)));
    if (daily.length < 2 || aave.length < 2) return unavailable("Insufficient aligned complete-day history");
    if (daily.length !== aave.length) return unavailable("Daily and Aave history lengths differ");

    const latest = daily.at(-1);
    const previous = daily.at(-2);
    const latestAave = aave.at(-1);
    const previousAave = aave.at(-2);
    if (latest.date !== latestAave.date || previous.date !== previousAave.date) {
      return unavailable("Daily and Aave dates are not aligned");
    }

    const today = utcDay(now).toISOString().slice(0, 10);
    if (latest.date >= today) {
      return unavailable(`Current/ future UTC day ${latest.date} cannot be treated as complete`, "PARTIAL_DAY");
    }

    const locatorRecords = locators?.records;
    const latestLocator = Array.isArray(locatorRecords) ? locatorRecords.at(-1) : null;
    if (!latestLocator || latestLocator.date !== latest.date) {
      return unavailable("Latest evidence locator is not aligned to canonical latest day");
    }
    if (locators.record_count !== index?.coverage?.day_count || index.coverage.last_date !== latest.date) {
      return unavailable("Canonical coverage identity is inconsistent");
    }
    if (!(latestLocator.from_block <= latestLocator.to_block)) {
      return unavailable("Invalid finalized block range");
    }

    const boundary = contractBoundary(contracts);
    const segmentStart = boundary && boundary.date <= latest.date ? boundary.date : null;
    const currentMetrics = metricsFrom(latestAave, latest);
    const previousMetrics = metricsFrom(previousAave, previous);
    const crossesBoundary = Boolean(segmentStart && previous.date < segmentStart);

    const priorDays = daily.slice(0, -1).filter((row) => !segmentStart || row.date >= segmentStart).slice(-7);
    const aaveByDate = new Map(aave.map((row) => [row.date, row]));
    const averages = {};
    for (const [, key] of METRICS) {
      const values = priorDays.map((row) => {
        const aaveRow = aaveByDate.get(row.date);
        return key === "swaps" ? row.uniswap_swap_count : aaveRow.event_counts[key];
      });
      averages[key] = mean(values);
    }

    const historyRows = daily.filter((row) => !segmentStart || row.date >= segmentStart).slice(-30);
    const history = METRICS.map(([label, key]) => ({
      label,
      key,
      points: historyRows.map((row) => {
        const aaveRow = aaveByDate.get(row.date);
        return [row.date, key === "swaps" ? row.uniswap_swap_count : aaveRow.event_counts[key]];
      }),
    }));

    const comparison = crossesBoundary ? null : METRICS.map(([label, key]) => ({
      label,
      key,
      previous: previousMetrics[key],
      previous_delta_pct: percent(currentMetrics[key], previousMetrics[key]),
      prior7_average: averages[key],
      prior7_delta_pct: averages[key] == null ? null : percent(currentMetrics[key], averages[key]),
    }));

    const codes = [];
    const expectedLatest = shiftDay(today, -1);
    if (latest.date < expectedLatest) codes.push("STALE");
    if (segmentStart && historyRows.some((row) => row.date === segmentStart)) codes.push("CONTRACT_CHANGE");
    if (!crossesBoundary && METRICS.every(([, key]) => currentMetrics[key] === previousMetrics[key])) codes.push("NO_CHANGE");
    if (!codes.length) codes.push("CURRENT");

    const statusMessages = {
      CURRENT: "Latest complete UTC day is current and comparable.",
      NO_CHANGE: "Headline counts match the previous complete UTC day.",
      STALE: `Latest canonical complete day ${latest.date} is older than expected ${expectedLatest}.`,
      CONTRACT_CHANGE: `Contract identity changed at the ${segmentStart} observation boundary; history is not silently joined across it.`,
    };

    return {
      displayable: true,
      status: {
        kind: codes[0],
        codes,
        message: codes.map((code) => statusMessages[code]).join(" "),
      },
      latest_date: latest.date,
      previous_date: previous.date,
      headline: currentMetrics,
      comparison,
      history,
      contract_boundary: segmentStart ? boundary : null,
      evidence: latestLocator,
      retrieved_at: index.retrieved_at,
      coverage: index.coverage,
    };
  } catch (error) {
    return unavailable(error instanceof Error ? error.message : String(error));
  }
}

export function formatDelta(value) {
  if (value == null) return "—";
  return `${value > 0 ? "+" : ""}${value.toFixed(1)}%`;
}
