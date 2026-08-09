/* Asserts the JS engine reproduces the frozen Python output.

   data/engine-fixture.json is ground truth, captured before the Python
   engine was deleted. Regenerate it only when the model deliberately
   changes -- never to make a failing port pass. */
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
