# JS Cost Engine Implementation Plan (PR A)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move the cost-per-mile calculation from `build.py` into the browser so that assumptions can later become editable, with no visible change to the published page.

**Architecture:** A new `engine.js` becomes the single cost implementation. `build.py` stops computing cost and instead emits raw vehicle rows plus `data/inputs.json`, then inlines `engine.js` into `index.html` at build time so the page stays a single dependency-free file. `test_build.py` keeps its published-workbook oracle by shelling out to Node.

**Tech Stack:** Python 3.8+ standard library (build and test harness), plain ES5-compatible JavaScript (engine and page, matching the existing `var`-style code), Node 20+ (test only, never shipped).

## Global Constraints

- The published page must have **zero runtime dependencies**. Node is a development dependency only.
- **No rounding inside the engine.** Python `round()` is half-to-even, `Math.round` is not. Round only at display.
- **Transliterate, do not improve.** Identical expression order in both languages. Any refactor happens after parity is proven, in a separate commit.
- `python3 test_build.py` remains the single test entry point, as the README promises and CI (#14) will run.
- The acceptance criterion for this whole PR is **"nothing visible changed"**.
- `data/engine-fixture.json` is ground truth. Regenerate it only if the model deliberately changes, **never** to make a failing port pass.
- Existing JS is ES5-style (`var`, `function`). Match it; do not introduce `const`/arrow functions into `index.html`.

---

### Task 1: Emit the raw fields the engine will need

The page currently carries `price`, `mpg`, and `fuel` but not `deprec_5yr`, `tire_class`, `observed_price`, or `observed_price_odometer`. In Python a missing field raises `KeyError`; in JS `undefined * 2` is `NaN`, which renders a silently broken chart. Add the fields and a schema assertion before any engine exists.

**Files:**
- Modify: `build.py` (`build_models`, and add `REQUIRED_ENGINE_FIELDS`)
- Modify: `data/vehicles.csv` (add `observed_price_odometer` column)
- Test: `test_build.py` (add `check_emitted_schema`)

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `build.REQUIRED_ENGINE_FIELDS` (a `tuple[str, ...]`), and each emitted model dict gains keys `deprec5yr` (float), `tireClass` (str), `observedPrice` (float or `None`), `observedAt` (float or `None`).

- [ ] **Step 1: Add the anchor column to the data**

```bash
python3 - <<'PY'
import csv, pathlib
p = pathlib.Path('data/vehicles.csv')
rows = list(csv.DictReader(open(p)))
cols = list(rows[0].keys())
if 'observed_price_odometer' not in cols:
    cols.insert(cols.index('observed_price') + 1, 'observed_price_odometer')
for r in rows:
    r.setdefault('observed_price_odometer', '')
    # Every existing observed price was sourced at the 40,000-mile buy point.
    if r.get('observed_price'):
        r['observed_price_odometer'] = 40000
with open(p, 'w', newline='') as fh:
    w = csv.DictWriter(fh, fieldnames=cols); w.writeheader(); w.writerows(rows)
print('anchored', sum(1 for r in rows if r.get('observed_price')), 'rows')
PY
```

Expected: `anchored 4 rows`

- [ ] **Step 2: Write the failing schema test**

Add to `test_build.py`, and call it from `main()` immediately after `check_price_resolution()`:

```python
def check_emitted_schema(rows):
    """Every field the JS engine reads must reach the page.

    Python raises KeyError on a missing field. JS computes undefined * 2 = NaN
    and renders a broken chart with no error, so absence has to be caught here.
    """
    models = build.build_models(rows, build.INPUTS)
    for m in models:
        missing = [f for f in build.REQUIRED_ENGINE_FIELDS if f not in m]
        assert not missing, f'{m["name"]}: emitted row lacks {missing}'
        assert isinstance(m['deprec5yr'], float), \
            f'{m["name"]}: deprec5yr must be numeric, got {m["deprec5yr"]!r}'
        assert m['tireClass'] in ('Truck', 'Crossover'), \
            f'{m["name"]}: unexpected tireClass {m["tireClass"]!r}'
        if m['observedPrice'] is not None:
            assert m['observedAt'], \
                f'{m["name"]}: observedPrice without observedAt anchor'
```

- [ ] **Step 3: Run it and watch it fail**

Run: `python3 test_build.py`
Expected: FAIL with `AttributeError: module 'build' has no attribute 'REQUIRED_ENGINE_FIELDS'`

- [ ] **Step 4: Add the constant and emit the fields**

In `build.py`, after the `MARKER` definition:

```python
# Fields engine.js reads. Absence is a NaN in the browser, not an exception,
# so test_build.py asserts every one of these reaches the page.
REQUIRED_ENGINE_FIELDS = ('price', 'mpg', 'fuel', 'deprec5yr', 'tireClass',
                          'observedPrice', 'observedAt')
```

In `build_models`, inside the appended dict, after `'gvwr': v['gvwr_note'],`:

```python
            'deprec5yr': float(v['deprec_5yr']),
            'tireClass': 'Truck' if v['tire_class'] == 'Truck' else 'Crossover',
            'observedPrice': float(v['observed_price']) if v.get('observed_price') else None,
            'observedAt': float(v['observed_price_odometer']) if v.get('observed_price_odometer') else None,
```

- [ ] **Step 5: Run the tests**

Run: `python3 build.py && python3 test_build.py`
Expected: PASS, `79 vehicles, 4 observed / 75 placeholder`

- [ ] **Step 6: Commit**

```bash
git add build.py test_build.py data/vehicles.csv index.html
git commit -m "feat: emit the raw fields the JS engine will need

Adds deprec5yr, tireClass, observedPrice, and observedAt to each emitted
row, plus observed_price_odometer to the CSV so every price carries the
mileage it was measured at.

check_emitted_schema asserts all of them reach the page. A missing field
raises KeyError in Python but produces NaN in JS, which renders a broken
chart with no error."
```

---

### Task 2: Port the engine to JS and prove parity against the fixture

`data/engine-fixture.json` holds the Python engine's raw unrounded output for all 79 vehicles, in two variants. This task writes the JS and proves it reproduces those numbers to 1e-12. **Do not delete any Python yet.**

**Files:**
- Create: `engine.js`
- Create: `test_engine.mjs`
- Modify: `test_build.py` (add `check_js_engine_parity`)

**Interfaces:**
- Consumes: `build.REQUIRED_ENGINE_FIELDS` from Task 1; `data/engine-fixture.json`.
- Produces: `engine.js` exporting `VA.retentionIndex(odometer, anchors)`, `VA.repairReserve(inputs)`, `VA.buyPrice(vehicle, inputs)` returning `{price, basis}`, and `VA.costPerMile(vehicle, inputs)` returning a raw unrounded number.

- [ ] **Step 1: Write `engine.js` as a direct transliteration**

```javascript
/* Cost engine. The single implementation -- build.py inlines this into
   index.html, and test_engine.mjs imports it directly.

   Transliterated from the Python that produced data/engine-fixture.json.
   Expression order is deliberately identical: both runtimes use IEEE-754
   doubles, so matching order gives matching results. NO ROUNDING happens
   here. Python's round() is half-to-even and Math.round is not, so rounding
   lives at the display layer only. */
var VA = (function () {
  function retentionIndex(odometer, anchors) {
    var base = anchors[0][1];
    if (odometer <= anchors[0][0]) return anchors[0][1] / base;
    for (var i = 0; i < anchors.length - 1; i++) {
      var x0 = anchors[i][0], y0 = anchors[i][1];
      var x1 = anchors[i + 1][0], y1 = anchors[i + 1][1];
      if (odometer <= x1) {
        var span = (odometer - x0) / (x1 - x0);
        return (y0 + span * (y1 - y0)) / base;
      }
    }
    return anchors[anchors.length - 1][1] / base;
  }

  function repairReserve(inp) {
    var buy = inp.buy_odometer, sell = inp.sell_odometer;
    var r = inp.repair_reserve_per_mile;
    var bands = [
      [Math.max(0, Math.min(sell, 100000) - buy), r.under_100k],
      [Math.max(0, Math.min(sell, 150000) - Math.max(buy, 100000)), r['100k_to_150k']],
      [Math.max(0, sell - Math.max(buy, 150000)), r.over_150k]
    ];
    var total = 0;
    for (var i = 0; i < bands.length; i++) total += bands[i][0] * bands[i][1];
    return total / (sell - buy);
  }

  function resaleMultiplier(v, inp) {
    return (1 - v.deprec5yr) / (1 - inp.industry_avg_5yr_deprec);
  }

  function buyPrice(v, inp) {
    if (v.observedPrice) return { price: v.observedPrice, basis: 'observed' };
    return { price: v.price, basis: 'placeholder' };
  }

  function costPerMile(v, inp) {
    var miles = inp.sell_odometer - inp.buy_odometer;
    var years = miles / inp.annual_miles;
    var anchors = inp.retention_anchors;

    var price = buyPrice(v, inp).price;
    var resaleMult = resaleMultiplier(v, inp);
    var ratio = retentionIndex(inp.sell_odometer, anchors)
              / retentionIndex(inp.buy_odometer, anchors);
    var resale = Math.min(price, price * ratio * resaleMult);

    var fuel = (v.fuel === 'Diesel' ? inp.diesel_per_gal : inp.gas_per_gal) / v.mpg;
    var tires = (v.tireClass === 'Truck' ? inp.tire_set_truck
                                         : inp.tire_set_crossover) / inp.tire_life_miles;

    var capital;
    if (inp.financing_mode === 'cash') {
      capital = (price + resale) / 2 * inp.cash_opportunity_rate;
    } else {
      var financed = price * (1 - inp.down_payment_pct);
      capital = financed * inp.avg_outstanding_balance_factor * inp.loan_apr
              + price * inp.down_payment_pct * inp.cash_opportunity_rate;
    }

    return (price - resale) / miles
         + fuel + tires
         + inp.scheduled_maint_per_mile
         + repairReserve(inp)
         + (inp.insurance_per_year + inp.registration_per_year) / inp.annual_miles
         + price * inp.sales_tax_rate / miles
         + capital * years / miles;
  }

  return {
    retentionIndex: retentionIndex,
    repairReserve: repairReserve,
    resaleMultiplier: resaleMultiplier,
    buyPrice: buyPrice,
    costPerMile: costPerMile
  };
})();

if (typeof module !== 'undefined' && module.exports) module.exports = VA;
```

- [ ] **Step 2: Write the Node parity harness**

Create `test_engine.mjs`:

```javascript
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
const models = JSON.parse(readFileSync('./build-models.json', 'utf8'));

const TOL = 1e-12;
let checked = 0, worst = 0, worstName = '';

for (const variant of ['full', 'workbook_oracle']) {
  for (const m of models) {
    // The oracle variant is computed with observed prices stripped, exactly
    // as test_build.py strips them to compare against the workbook.
    const v = variant === 'workbook_oracle'
      ? { ...m, observedPrice: null }
      : m;
    const expected = fixture[variant][m.name];
    if (!expected) throw new Error(`fixture has no ${variant} entry for ${m.name}`);
    const got = VA.costPerMile(v, inputs);
    if (!Number.isFinite(got)) throw new Error(`${m.name} (${variant}): got ${got}`);
    const delta = Math.abs(got - expected.cpm);
    if (delta > worst) { worst = delta; worstName = `${m.name} (${variant})`; }
    if (delta > TOL) {
      throw new Error(
        `${m.name} (${variant}): JS ${got} vs Python ${expected.cpm}, delta ${delta}`);
    }
    checked++;
  }
}
console.log(`ok: ${checked} comparisons within ${TOL}, worst ${worst.toExponential(2)} (${worstName})`);
```

- [ ] **Step 3: Run it and watch it fail**

Run: `node test_engine.mjs`
Expected: FAIL with `ENOENT: no such file or directory, open './build-models.json'`

- [ ] **Step 4: Have the Python harness produce the model dump and invoke Node**

Add to `test_build.py`, called from `main()` after `check_emitted_schema(real)`:

```python
def check_js_engine_parity(rows):
    """Run engine.js under Node against the frozen Python output.

    The 11 workbook figures prove the formula; this proves the port. Both are
    needed -- the workbook covers 11 of 79 vehicles at one input set.

    A missing Node must fail rather than skip. A skipped check reads exactly
    like a passing one.
    """
    import json
    import shutil
    import subprocess
    import tempfile

    node = shutil.which('node')
    assert node, ('node is required to test the cost engine and was not found. '
                  'It is a development dependency only; the page ships without it.')

    root = pathlib.Path(__file__).parent
    models = build.build_models(rows, build.INPUTS)
    dump = root / 'build-models.json'
    dump.write_text(json.dumps(models))
    try:
        r = subprocess.run([node, str(root / 'test_engine.mjs')],
                           cwd=root, capture_output=True, text=True)
    finally:
        dump.unlink(missing_ok=True)
    assert r.returncode == 0, f'JS engine parity failed:\n{r.stdout}{r.stderr}'
    print(f'  {r.stdout.strip()}')
```

Add `build-models.json` to `.gitignore`.

- [ ] **Step 5: Run the tests**

Run: `python3 test_build.py`
Expected: PASS, including a line like `ok: 158 comparisons within 1e-12, worst 0.00e+0`

If any comparison fails, the port is wrong — fix `engine.js`, never the fixture.

- [ ] **Step 6: Commit**

```bash
git add engine.js test_engine.mjs test_build.py .gitignore
git commit -m "feat: port the cost engine to JS, gated on fixture parity

engine.js is a direct transliteration of the Python, with identical
expression order and no rounding, so both IEEE-754 runtimes agree.

test_engine.mjs asserts it reproduces data/engine-fixture.json for all 79
vehicles in both variants to within 1e-12, driven from test_build.py so
python3 test_build.py stays the single entry point. A missing node fails
rather than skips.

No Python is deleted yet and the page is unchanged."
```

---

### Task 3: Inline the engine into the page and compute cost in the browser

**Files:**
- Modify: `build.py` (`render`, `build_models`)
- Modify: `index.html` (`compute()`)
- Test: `test_build.py` (extend `check_emitted_schema`)

**Interfaces:**
- Consumes: `VA.costPerMile` from Task 2.
- Produces: page-global `INPUTS` object; `compute()` populates `m.cpm`, `m.peryr`, and `m.cost` at runtime.

- [ ] **Step 1: Inline `engine.js` and emit `INPUTS`**

In `build.py`, replace `render` with:

```python
def render(html, models, inputs, engine_src):
    """Inline the engine, the inputs, and the raw rows into the page.

    engine.js is a real source file so the Node test can import it directly
    rather than scraping a <script> block out of the HTML. Inlining here is
    what keeps the published page a single file with no dependencies.
    """
    start = html.index(MARKER)
    end = html.index('];', start) + 2
    payload = json.dumps(models, separators=(',', ':'), ensure_ascii=False)
    block = (engine_src.rstrip() + '\n'
             + 'const INPUTS = ' + json.dumps(inputs, separators=(',', ':')) + ';\n'
             + MARKER + payload + ';')
    return html[:start] + block + html[end:]
```

`render` must be idempotent. The engine block is re-emitted on every build, so `MARKER` must remain the first thing replaced — locate `start` from `MARKER`, and strip any previously inlined engine by searching backwards for the engine sentinel:

```python
    ENGINE_START = '/* Cost engine.'
    if ENGINE_START in html:
        start = html.index(ENGINE_START)
    else:
        start = html.index(MARKER)
```

- [ ] **Step 2: Stop computing cost in Python**

In `build_models`, delete the `cpms`, `lo`, `hi` computation and the `cpm`, `peryr`, `cost` keys from the emitted dict. Keep `mpgs`/`mlo`/`mhi` and `efficiency` — efficiency depends only on MPG, which is not an input, so it stays a build-time value.

- [ ] **Step 3: Compute cost at the head of `compute()`**

In `index.html`, at the start of `compute()`:

```javascript
function compute(){
  var raw=MODELS.map(function(m){return VA.costPerMile(m,INPUTS)});
  var lo=Math.min.apply(null,raw), hi=Math.max.apply(null,raw);
  MODELS.forEach(function(m,i){
    m.cpm=raw[i];
    m.peryr=raw[i]*INPUTS.annual_miles;
    m.cost=hi===lo?100:100*(hi-raw[i])/(hi-lo);
  });
  var bad=MODELS.filter(function(m){return !isFinite(m.cpm)});
  if(bad.length){
    document.getElementById('frontStat').textContent=
      'Cost engine error: '+bad.length+' vehicles produced no result';
    throw new Error('non-finite cpm: '+bad.map(function(m){return m.name}).join(', '));
  }
  var pool=MODELS.filter(function(m){return passes(m,FILT)});
  /* ...rest unchanged... */
```

Round only where displayed: the detail card and the ranked list already format their own values, so change those call sites to `.toFixed(3)` and `Math.round()` rather than relying on pre-rounded data.

- [ ] **Step 4: Run the tests and check the page**

Run: `python3 build.py && python3 test_build.py && node -e "1"`
Then open `index.html` in a browser: chart draws, `Frontier · 4 of 79 undominated`, the filter chips still redraw.

- [ ] **Step 5: Prove nothing visible changed**

```bash
python3 - <<'PY'
import json, re, subprocess, urllib.request
live = urllib.request.urlopen('https://dbeihl.github.io/vehicle-analysis/').read().decode()
old = {m['name']: m for m in json.loads(re.search(r'const MODELS = (\[.*?\]);', live, re.S).group(1))}
subprocess.run(['python3', 'build.py'], check=True)
new = json.loads(re.search(r'const MODELS = (\[.*?\]);', open('index.html').read(), re.S).group(1))
import importlib, build; importlib.reload(build)
worst = 0
for m in new:
    o = old[m['name']]
    for k in ('quality', 'longevity', 'reliability', 'comfort', 'efficiency', 'price'):
        assert o[k] == m[k], f"{m['name']}.{k}: {o[k]} -> {m[k]}"
print(f'{len(new)} rows: every non-computed field identical to the live page')
PY
```

Expected: `79 rows: every non-computed field identical to the live page`

- [ ] **Step 6: Commit**

```bash
git add build.py index.html test_build.py
git commit -m "feat: compute cost per mile in the browser

build.py inlines engine.js and emits INPUTS alongside the raw rows; the
page computes cpm, peryr, and the 0-100 cost axis at the head of compute().
Rounding moved to the display layer.

compute() throws and shows an error banner if any vehicle produces a
non-finite cost, because a NaN would otherwise render as a silently grey
chart rather than a failure."
```

---

### Task 4: Delete the Python engine and repoint the oracle

Only now, with parity proven and the page rendering from JS.

**Files:**
- Modify: `build.py` (delete `cost_per_mile`, `retention_index`, `repair_reserve`, `resale_multiplier`)
- Modify: `test_build.py` (`main`, `check_price_resolution`)
- Modify: `test_engine.mjs` (assert the workbook figures)
- Modify: `README.md`

**Interfaces:**
- Consumes: `VA.costPerMile` via Node.
- Produces: `build.buy_price` and `build.price_problems` survive; every other cost function is gone.

- [ ] **Step 1: Move the workbook oracle into the Node harness**

Append to `test_engine.mjs`:

```javascript
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
```

- [ ] **Step 2: Run it and confirm both checks pass**

Run: `python3 test_build.py`
Expected: PASS, with both the parity line and the published-figures line.

- [ ] **Step 3: Delete the Python engine**

Remove `cost_per_mile`, `retention_index`, `repair_reserve`, and `resale_multiplier` from `build.py`. In `test_build.py`, delete `PUBLISHED_CPM`, the loop that uses it, and the `EXPECTED_WINNER`/`EXPECTED_SCORE`/`EXPECTED_FRONTIER` blocks that depend on Python-computed `cost` — those assertions now live in `test_engine.mjs`. Port the balanced-six winner and frontier assertions there using the same weights.

Keep `buy_price`, `price_problems`, `num`, `scale`, `load`, `build_models`, `render`, and `main`.

- [ ] **Step 4: Run everything**

Run: `python3 build.py --check && python3 test_build.py`
Expected: PASS. Confirm `grep -c 'def cost_per_mile' build.py` returns `0`.

- [ ] **Step 5: Update the README**

Change the `build.py` row to "Emits the dataset and inlines the engine into `index.html`", add an `engine.js` row reading "The cost model. The only implementation; inlined into the page at build", and add a `test_engine.mjs` row. Update the prerequisites line to note that **Node 20+ is required to run the tests but not to use the page**. Update the "Modifying the data" section: `python3 test_build.py` still runs everything.

Then run `dd-toolkit:humanizer` over the changed prose.

- [ ] **Step 6: Commit and open the PR**

```bash
git add build.py test_build.py test_engine.mjs README.md index.html
git commit -m "refactor: delete the Python cost engine

engine.js is now the only implementation. The workbook's 11 published
\$/mile figures, the balanced-six winner, and the frontier set moved into
test_engine.mjs, so the oracle survives the deletion -- it was always the
spreadsheet's numbers rather than the Python that read them.

python3 test_build.py remains the single entry point and shells out to node."
gh pr create --base main --title "Port the cost engine to JS (no visible change)" --body "..."
```

Then run `codex-review` per the standing rule, and iterate to approve.

---

## Self-review

**Spec coverage.** This plan covers spec sections 1 (engine to browser), 2 (verification survives), and the `observed_price_odometer` column from section 3. Spec sections 4 (panel), 5 (provenance display), and 6 (URL state) are **PR B** and get their own plan once this merges. Section 3's price *scaling* is deliberately deferred to PR B: adding it here would change visible numbers and break this PR's "nothing visible changed" gate. Task 1 lands the column so PR B has the data.

**Placeholders.** None. Every step carries the code or command to run.

**Type consistency.** `deprec5yr`, `tireClass`, `observedPrice`, `observedAt` are named identically in Task 1's emitter, Task 1's assertion, Task 2's engine, and Task 3's `compute()`. `VA.costPerMile(vehicle, inputs)` has the same signature everywhere. `buyPrice` returns `{price, basis}` in Task 2 and is only destructured as `.price` in `costPerMile`.

**Known gap, deliberate.** `buyPrice` in Task 2 ignores `observedAt` — it is a straight transliteration of today's Python, which has no scaling. PR B adds the scaling, and that is when `observedAt` starts being read.
