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
  for (const m of models) seen.add(m.name);
  const missing = expectedNames.filter(name => !seen.has(name));
  if (missing.length > 0) {
    throw new Error(`${variant}: fixture entries never compared: ${missing.join(', ')}`);
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
    const expected = fixture[variant][v.name];
    if (!expected) throw new Error(`fixture has no ${variant} entry for ${v.name}`);
    const got = VA.costPerMile(v, inputs);
    if (!Number.isFinite(got)) throw new Error(`${v.name} (${variant}): got ${got}`);
    const delta = Math.abs(got - expected.cpm);
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
  'Honda HR-V': 0.426, 'Ford Escape Hybrid': 0.441, 'Toyota Venza': 0.457,
  'Nissan Rogue': 0.459, 'Ford Maverick Hybrid': 0.460,
  'Toyota Highlander Hybrid': 0.517, 'Honda Ridgeline': 0.519,
  'Toyota Grand Highlander Hybrid': 0.580, 'Chevrolet Tahoe': 0.674,
  'Chevrolet Tahoe 3.0L Duramax': 0.703,
  'Toyota Sequoia (pre-2023 5.7 V8)': 0.717
};
for (const [name, expected] of Object.entries(PUBLISHED)) {
  const m = models.find(x => x.name === name);
  if (!m) throw new Error(`${name} missing from the dataset`);
  const got = VA.costPerMile({ ...m, observedPrice: null }, inputs);
  if (Math.abs(got - expected) >= 0.001) {
    throw new Error(`${name}: workbook says ${expected}/mi, engine computes ${got}`);
  }
}
console.log(`ok: ${Object.keys(PUBLISHED).length} published $/mile figures match`);

// StrategyMatrix "Balanced six": winner, score, and the efficient frontier.
// Ported from test_build.py's former Python assertions -- cost/cpm are
// computed client-side now (VA.costPerMile), so this reproduces the 0-100
// cost score build.scale() used to bake into the emitted dict, against the
// workbook_oracle variant's own cpm range (same 79 rows the Python version
// scaled against).
function scale(value, lo, hi, invert) {
  if (hi === lo) return 100.0;
  const pct = (invert ? hi - value : value - lo) / (hi - lo);
  return Math.round(pct * 1000) / 10;
}

// Same weights INPUTS already carries as default_weights, not re-typed here.
const BALANCED = inputs.default_weights;
const EXPECTED_WINNER = 'Toyota Highlander Hybrid';
const EXPECTED_SCORE = 89.9;
const EXPECTED_FRONTIER = new Set([
  'Toyota Highlander Hybrid', 'Toyota Venza', 'Ford Escape Hybrid', 'Honda HR-V'
]);

const cpms = models.map(m => VA.costPerMile(m, inputs));
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
  )).map(m => m.name)
);
const frontierOk = frontier.size === EXPECTED_FRONTIER.size &&
  [...frontier].every(n => EXPECTED_FRONTIER.has(n));
if (!frontierOk) {
  throw new Error(`frontier changed: ${[...frontier].sort()} != ${[...EXPECTED_FRONTIER].sort()}`);
}
console.log(`ok: balanced-six = ${winner} at ${winnerScore.toFixed(1)}, frontier = ${[...frontier].sort().join(', ')}`);
