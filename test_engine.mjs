/* Asserts the JS engine reproduces the frozen Python output. That output is
   now also the regression baseline for engine.js and the data.

   data/engine-fixture.json was captured before the Python engine was
   deleted, proving the JS port. A deliberate change to the model or to a
   vehicle's price requires regenerating it: `python3 freeze_fixture.py`.
   Never regenerate it just to make a failing port pass. */
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const VA = require('./engine.js');
const fixture = JSON.parse(readFileSync('./data/engine-fixture.json', 'utf8'));
const inputs = fixture._inputs;
const dumped = JSON.parse(readFileSync('./build-models.json', 'utf8'));

/* The workbook has no reliability term. Every assertion below that derives
   from the spreadsheet -- the frozen oracle variant, the 11 published
   figures, the balanced-six winner, the frontier -- runs at a neutral
   spread, mirroring build.oracle_inputs() on the Python side. */
const ORACLE_INPUTS = { ...inputs, repair_cost_spread_ratio: 1 };
const INPUTS_FOR = { full: inputs, workbook_oracle: ORACLE_INPUTS };

const TOL = 1e-12;
let checked = 0, worst = -Infinity, worstName = '';

// Structural checks on the dump for one variant, run once before its
// per-vehicle parity loop below. Checking only for a non-empty `models`
// array is not enough: a dump truncated to 39 of 79 rows is still non-empty,
// and the loop underneath would happily report "ok" having compared fewer
// than half the fixture -- an under-test wearing a pass. The invariant that
// actually matters is coverage of ground truth, so this compares against
// data/engine-fixture.json itself, not against whatever the caller dumped.
// Later tasks append further per-variant assertions here rather than inline
// in the loop, so they stay in one place as the fixture grows.
function assertVariantShape(variant, models) {
  const expectedNames = Object.keys(fixture[variant]);
  if (models.length !== expectedNames.length) {
    throw new Error(
      `${variant}: dumped ${models.length} models, fixture has ${expectedNames.length} -- ` +
      `every fixture entry must be compared`);
  }
  // Cheap reverse check: same count could still hide a substitution (a
  // duplicated name in place of a missing one). Confirm every fixture name
  // was actually present in the dump, not just that the counts matched.
  const seen = new Set();
  for (const m of models) seen.add(m.key);
  const missing = expectedNames.filter(name => !seen.has(name));
  if (missing.length > 0) {
    throw new Error(`${variant}: fixture entries never compared: ${missing.join(', ')}`);
  }

  /* Independence check. build.strip_for_oracle() is used BOTH by
     freeze_fixture.py to generate the oracle variant and by test_build.py to
     produce the dump checked against it, so a bug there would bake into
     ground truth and its own checker symmetrically and still report a clean
     1e-12 match. Asserting the property here -- rather than trusting the
     function that produced both sides -- is what keeps the check honest.
     See issue #18. */
  if (variant === 'workbook_oracle') {
    const leaked = models.filter(m => m.observedPrice !== null
                                   && m.observedPrice !== undefined);
    if (leaked.length > 0) {
      throw new Error(
        `workbook_oracle: observed prices were not stripped from ` +
        `${leaked.map(m => m.name).join(', ')} -- the workbook figures were ` +
        `computed on placeholder prices, so this variant must carry none`);
    }
  }
}

for (const variant of ['full', 'workbook_oracle']) {
  // Both variants come pre-built from test_build.py: 'full' from the real
  // rows, 'workbook_oracle' from rows with observed_price stripped before
  // build_models runs (same idiom main() uses against the workbook). Each
  // model's 'price' field is therefore already correct for its variant --
  // build_models resolves buy_price into 'price', so stripping observedPrice
  // after the fact on a 'full' model cannot recover the raw placeholder.
  const models = dumped[variant];
  assertVariantShape(variant, models);

  for (const v of models) {
    const expected = fixture[variant][v.key];
    if (!expected) throw new Error(`fixture has no ${variant} entry for ${v.name}`);
    const got = VA.costPerMile(v, INPUTS_FOR[variant]);
    if (!Number.isFinite(got)) throw new Error(`${v.name} (${variant}): got ${got}`);
    const delta = Math.abs(got - expected.cpm);
    /* The oracle variant is frozen at a neutral spread, and multiplying by
       exactly 1.0 is exact in IEEE-754. So this variant must match to the
       bit, not to a tolerance -- any drift at all means the multiplier is
       not neutral at 1 and every workbook assertion below is running
       against a formula the spreadsheet never implemented. */
    if (variant === 'workbook_oracle' && delta !== 0) {
      throw new Error(`${v.name}: neutral spread moved the figure by ${delta} -- `
        + `it must be bit-for-bit identical`);
    }
    if (delta > worst) { worst = delta; worstName = `${v.name} (${variant})`; }
    if (delta > TOL) {
      throw new Error(
        `${v.name} (${variant}): JS ${got} vs Python ${expected.cpm}, delta ${delta}`);
    }
    checked++;
  }
}
console.log(`ok: ${checked} comparisons within ${TOL}, worst ${worst.toExponential(2)} (${worstName})`);

// Everything below runs against the workbook_oracle variant only: build_models()
// output with observed_price stripped before build ran, same as main()'s former
// workbook comparison. Two of the 79 rows (Highlander Hybrid, Venza) carry an
// observed price today -- using 'full' here would silently swap the workbook's
// placeholder price for the observed one on exactly the vehicles this oracle
// exists to check.
const models = dumped.workbook_oracle;

/* The workbook's independently computed figures. These come from ~3,170
   spreadsheet formulas, so they are the only oracle not written by this
   codebase. Computed on placeholder prices, hence the stripped variant. */
const PUBLISHED = {
  'Honda HR-V|unspecified': 0.426, 'Ford Escape Hybrid|unspecified': 0.441,
  'Toyota Venza|unspecified': 0.457, 'Nissan Rogue|unspecified': 0.459,
  'Ford Maverick Hybrid|unspecified': 0.460,
  'Toyota Highlander Hybrid|unspecified': 0.517, 'Honda Ridgeline|unspecified': 0.519,
  'Toyota Grand Highlander Hybrid|unspecified': 0.580, 'Chevrolet Tahoe|unspecified': 0.674,
  'Chevrolet Tahoe 3.0L Duramax|unspecified': 0.703,
  'Toyota Sequoia (pre-2023 5.7 V8)|unspecified': 0.717
};
for (const [key, expected] of Object.entries(PUBLISHED)) {
  const m = models.find(x => x.key === key);
  if (!m) throw new Error(`${key} missing from the dataset`);
  const got = VA.costPerMile({ ...m, observedPrice: null }, ORACLE_INPUTS);
  if (Math.abs(got - expected) >= 0.001) {
    throw new Error(`${key}: workbook says ${expected}/mi, engine computes ${got}`);
  }
}
console.log(`ok: ${Object.keys(PUBLISHED).length} published $/mile figures match`);

// StrategyMatrix "Balanced six": winner, score, and the efficient frontier.
// Ported from test_build.py's former Python assertions -- cost/cpm are
// computed client-side now (VA.costPerMile), so this reproduces the 0-100
// cost score against the workbook_oracle variant's own cpm range (same 79
// rows the Python version scaled against). Deliberately unrounded and in the
// same multiply-then-divide order as index.html's compute() --
// `m.cost=hi===lo?100:100*(hi-raw[i])/(hi-lo)` -- so this exercises the same
// cost axis the page ships, not a rounded stand-in for it.
function scale(value, lo, hi, invert) {
  if (hi === lo) return 100.0;
  return invert ? 100 * (hi - value) / (hi - lo) : 100 * (value - lo) / (hi - lo);
}

// Same weights INPUTS already carries as default_weights, not re-typed here.
const BALANCED = inputs.default_weights;
const EXPECTED_WINNER = 'Toyota Highlander Hybrid';
const EXPECTED_SCORE = 89.9;
const EXPECTED_FRONTIER = new Set([
  'Toyota Highlander Hybrid|unspecified', 'Toyota Venza|unspecified',
  'Ford Escape Hybrid|unspecified', 'Honda HR-V|unspecified'
]);

const cpms = models.map(m => VA.costPerMile(m, ORACLE_INPUTS));
const lo = Math.min(...cpms), hi = Math.max(...cpms);
const scored = models.map((m, i) => Object.assign({}, m, { cost: scale(cpms[i], lo, hi, true) }));

let winner = null, winnerScore = -Infinity;
for (const m of scored) {
  const s = Object.keys(BALANCED).reduce((sum, k) => sum + BALANCED[k] * m[k], 0) / 100;
  if (s > winnerScore) { winnerScore = s; winner = m.name; }
}
if (winner !== EXPECTED_WINNER) {
  throw new Error(`balanced-six winner is ${winner}, workbook says ${EXPECTED_WINNER}`);
}
if (Math.abs(winnerScore - EXPECTED_SCORE) >= 0.05) {
  throw new Error(`balanced-six score ${winnerScore.toFixed(1)}, workbook says ${EXPECTED_SCORE}`);
}

// Reproduce the frontier the page draws: cost against the weighted value of
// the other five axes. Asserting the frontier is merely non-empty proves
// nothing -- the cheapest vehicle is undominated by construction.
const valueAxes = Object.keys(BALANCED).filter(k => k !== 'cost');
const valueTotal = valueAxes.reduce((s, k) => s + BALANCED[k], 0);
for (const m of scored) {
  m.value = valueAxes.reduce((s, k) => s + BALANCED[k] * m[k], 0) / valueTotal;
}

const frontier = new Set(
  scored.filter(m => !scored.some(o =>
    o !== m && o.cost >= m.cost && o.value >= m.value &&
    (o.cost > m.cost || o.value > m.value)
  )).map(m => m.key)
);
const frontierOk = frontier.size === EXPECTED_FRONTIER.size &&
  [...frontier].every(n => EXPECTED_FRONTIER.has(n));
if (!frontierOk) {
  throw new Error(`frontier changed: ${[...frontier].sort()} != ${[...EXPECTED_FRONTIER].sort()}`);
}
console.log(`ok: balanced-six = ${winner} at ${winnerScore.toFixed(1)}, frontier = ${[...frontier].sort().join(', ')}`);

/* CHARACTERIZATION PIN -- NOT AN ORACLE.
   Everything above runs on workbook_oracle at a neutral spread, which is
   what makes it independent of this codebase. That leaves the ranking the
   page actually ships -- the 'full' variant at the live ratio in
   data/inputs.json -- asserted by nothing at all: the multiplier could be
   dropped, doubled, or inverted and every assertion above would stay green.

   So these constants were produced by RUNNING this code, not by any outside
   source. They record what the model does today. When the model changes on
   purpose -- the ratio moves, engine.js changes, a vehicle's data is
   corrected -- these are expected to change: rerun, update them
   deliberately, and say so in the commit. That is the opposite of the
   workbook figures above, which are ground truth and must never be edited
   to make a failing engine pass. A diff here is not proof of a bug; it is
   proof that the shipped ranking moved, which is what nothing was
   reporting before. */
const LIVE_WINNER = 'Toyota Highlander Hybrid';
const LIVE_SCORE = 89.5;
const LIVE_FRONTIER = new Set([
  'Ford Escape Hybrid|unspecified', 'Ford Maverick Hybrid|unspecified',
  'Honda HR-V|unspecified', 'Toyota Highlander Hybrid|unspecified',
  'Toyota RAV4 Hybrid|unspecified', 'Toyota Venza|unspecified'
]);

// Reuses scale(), BALANCED, valueAxes and valueTotal above -- same axes, same
// order of operations as index.html's compute(). The only differences from
// the oracle block are the variant (full, observed prices intact) and the
// inputs (live, so the spread ratio is whatever data/inputs.json ships).
const liveModels = dumped.full;
const liveCpms = liveModels.map(m => VA.costPerMile(m, INPUTS_FOR.full));
const liveLo = Math.min(...liveCpms), liveHi = Math.max(...liveCpms);
const liveScored = liveModels.map((m, i) =>
  Object.assign({}, m, { cost: scale(liveCpms[i], liveLo, liveHi, true) }));

let liveWinner = null, liveWinnerScore = -Infinity;
for (const m of liveScored) {
  const s = Object.keys(BALANCED).reduce((sum, k) => sum + BALANCED[k] * m[k], 0) / 100;
  if (s > liveWinnerScore) { liveWinnerScore = s; liveWinner = m.name; }
}
if (liveWinner !== LIVE_WINNER) {
  throw new Error(`the shipped balanced-six winner is now ${liveWinner}, pinned at `
    + `${LIVE_WINNER}. If the model changed on purpose, rerun and repin`);
}
if (Math.abs(liveWinnerScore - LIVE_SCORE) >= 0.05) {
  throw new Error(`the shipped balanced-six score is now ${liveWinnerScore.toFixed(1)}, `
    + `pinned at ${LIVE_SCORE}. If the model changed on purpose, rerun and repin`);
}

for (const m of liveScored) {
  m.value = valueAxes.reduce((s, k) => s + BALANCED[k] * m[k], 0) / valueTotal;
}
const liveFrontier = new Set(
  liveScored.filter(m => !liveScored.some(o =>
    o !== m && o.cost >= m.cost && o.value >= m.value &&
    (o.cost > m.cost || o.value > m.value)
  )).map(m => m.key)
);
const liveFrontierOk = liveFrontier.size === LIVE_FRONTIER.size &&
  [...liveFrontier].every(n => LIVE_FRONTIER.has(n));
if (!liveFrontierOk) {
  throw new Error(`the shipped frontier is now ${[...liveFrontier].sort()}, pinned at `
    + `${[...LIVE_FRONTIER].sort()}. If the model changed on purpose, rerun and repin`);
}
console.log(`ok: shipped ranking pinned at ratio ${INPUTS_FOR.full.repair_cost_spread_ratio} `
  + `= ${liveWinner} at ${liveWinnerScore.toFixed(1)}, frontier of ${liveFrontier.size}`);

/* Price scaling. An observed price is measured at one odometer reading;
   moving the buy point must move the price along the retention curve, or the
   page shows a 40,000-mile price against a 70,000-mile buy point. */
const scaled = dumped.full.find(m => m.observedPrice);
if (!scaled) throw new Error('no observed-price vehicle to test scaling against');

const atAnchor = VA.buyPrice(scaled, inputs);
if (atAnchor.price !== scaled.observedPrice || atAnchor.basis !== 'observed') {
  throw new Error(`at its own anchor a price must be returned untouched and marked observed, got ${JSON.stringify(atAnchor)}`);
}

const moved = VA.buyPrice(scaled, { ...inputs, buy_odometer: 70000 });
const expected = scaled.observedPrice
  * VA.retentionIndex(70000, inputs.retention_anchors)
  / VA.retentionIndex(scaled.observedAt, inputs.retention_anchors);
if (Math.abs(moved.price - expected) > 1e-9) {
  throw new Error(`scaled price ${moved.price} != ${expected}`);
}
if (moved.basis !== 'derived') {
  throw new Error(`a scaled price must be marked derived, got ${moved.basis}`);
}
if (!(moved.price < scaled.observedPrice)) {
  throw new Error('a higher-mileage buy point must cost less');
}
console.log('ok: observed prices scale along the retention curve');

/* The multiplier's shape, pinned at five points. Neutral is 1, not 0:
   Math.pow(0, x) is 0 or Infinity, which would destroy the engine rather
   than turn the feature off. */
const MULT_CASES = [
  { ratio: 1,    reliability: 0,   want: 1 },
  { ratio: 1,    reliability: 100, want: 1 },
  { ratio: 2.66, reliability: 50,  want: 1 },
  { ratio: 2.66, reliability: 100, want: 1 / Math.sqrt(2.66) },
  { ratio: 2.66, reliability: 0,   want: Math.sqrt(2.66) },
];
for (const c of MULT_CASES) {
  const got = VA.repairMultiplier({ reliability: c.reliability },
                                  { repair_cost_spread_ratio: c.ratio });
  if (Math.abs(got - c.want) > 1e-12) {
    throw new Error(`repairMultiplier at ratio ${c.ratio}, reliability `
      + `${c.reliability}: got ${got}, want ${c.want}`);
  }
}
/* The ratio IS the worst-to-best spread across the full 0-100 scale. If the
   exponent's divisor drifts from 100 this is the assertion that catches it. */
const best = VA.repairMultiplier({ reliability: 100 }, { repair_cost_spread_ratio: 2.66 });
const worstRel = VA.repairMultiplier({ reliability: 0 }, { repair_cost_spread_ratio: 2.66 });
if (Math.abs(worstRel / best - 2.66) > 1e-12) {
  throw new Error(`worst/best spread is ${worstRel / best}, want the ratio itself, 2.66`);
}
console.log('ok: repair multiplier is neutral at 1 and spans the ratio at 2.66');

/* Wiring check. Every assertion above calls VA.repairMultiplier() directly, or
   runs costPerMile at ratio 1 where the multiplier is identically 1 for every
   reliability -- so deleting "* repairMultiplier(v, inp)" from costPerMile's
   sum would leave every one of them green. This is the one assertion that
   moves the ratio off 1 on a vehicle whose reliability isn't 50, so the
   multiplier is not 1 and its presence in the sum is actually observable. */
const wired = dumped.full.find(m => m.reliability !== 50);
if (!wired) throw new Error('no full-variant vehicle with reliability !== 50 to test wiring against');
const wiredNeutral = { ...inputs, repair_cost_spread_ratio: 1 };
const wiredTest = { ...inputs, repair_cost_spread_ratio: 2 };
const atNeutral = VA.costPerMile(wired, wiredNeutral);
const atTestRatio = VA.costPerMile(wired, wiredTest);
const wiredExpected = VA.repairReserve(inputs) * (VA.repairMultiplier(wired, wiredTest) - 1);
if (Math.abs((atTestRatio - atNeutral) - wiredExpected) > 1e-12) {
  throw new Error(`${wired.name}: costPerMile moved by ${atTestRatio - atNeutral} when the `
    + `spread ratio changed from 1 to 2, expected ${wiredExpected} -- repairMultiplier is `
    + `computed but not wired into costPerMile's sum`);
}
console.log('ok: repairMultiplier is wired into costPerMile\'s sum, not just callable standalone');

/* Per-model evidence where the model has enough of its own complaints to
   describe it; the brand-shaped prior only where it does not. The prior spans
   Toyota 85-100 against Jeep 17.4-42.4 with no overlap, so blending toward it
   would average across a badge -- which is the thing this change removes. */
const ANCHORS = [
  { share: 0.20, want: 100 },   // ANCHOR_LOW  -> best
  { share: 0.95, want: 0 },     // ANCHOR_HIGH -> worst
  { share: 0.575, want: 50 },   // midpoint
  { share: 0.05, want: 100 },   // below the low anchor clamps, never exceeds 100
  { share: 1.00, want: 0 },     // above the high anchor clamps, never goes negative
];
for (const c of ANCHORS) {
  const got = VA.complaintScore(c.share);
  if (Math.abs(got - c.want) > 1e-9) {
    throw new Error(`complaintScore(${c.share}) = ${got}, want ${c.want}`);
  }
}

const minInputs = { ...inputs, complaint_min_n: 40 };
const evidenced = { reliability: 100, complaintSeverity: 0.95, complaintN: 500 };
const thin     = { reliability: 100, complaintSeverity: 0.95, complaintN: 39 };
const none     = { reliability: 100, complaintSeverity: null, complaintN: 0 };

if (VA.repairReliability(evidenced, minInputs) !== 0) {
  throw new Error('a vehicle above the threshold must take its own evidence, '
    + 'not the prior');
}
if (VA.repairReliability(thin, minInputs) !== 100) {
  throw new Error('a vehicle one complaint below the threshold must take the prior');
}
if (VA.repairReliability(none, minInputs) !== 100) {
  throw new Error('a vehicle with no complaint data must take the prior');
}
/* The off switch is a large number, not zero -- opposite of the spread
   ratio, whose neutral is 1. Getting this backwards silently sends every
   vehicle to its evidence instead of away from it. */
const off = { ...inputs, complaint_min_n: 1e9 };
if (VA.repairReliability(evidenced, off) !== 100) {
  throw new Error('an impossibly high complaint_min_n must send every vehicle '
    + 'to the prior');
}
console.log('ok: per-model evidence above the threshold, prior below it');
