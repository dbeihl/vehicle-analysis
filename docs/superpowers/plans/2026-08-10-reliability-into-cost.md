# Reliability into cost implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Scale the repair reserve by each vehicle's reliability score, so maintenance stops being a constant that cannot change which vehicle wins.

**Architecture:** One new input, `repair_cost_spread_ratio`, multiplies the repair reserve by `ratio^((50 - reliability)/100)` at the call site in `costPerMile`. The workbook oracle runs at a neutral ratio of 1.0 across its whole path, because the spreadsheet has no reliability term. Task 1 ships the mechanism at neutral and proves it changes nothing; Task 2 turns it on.

**Tech Stack:** Vanilla ES5-style JS (`engine.js`, inlined into `index.html`), Python 3.8+ standard library (`build.py`), Node 20+ for the test oracles.

## Global Constraints

- Spec: `docs/superpowers/specs/2026-08-10-reliability-into-cost-design.md`
- Branch: `reliability-into-cost`. Never commit to `main`; the change reaches `main` through a PR.
- Default ratio: **2.66**, from RepairPal 2026 brand averages (Toyota $441/yr, Land Rover $1,174/yr).
- Neutral for this parameter is **1.0, not 0**. `Math.pow(0, x)` is 0 or Infinity and destroys the engine.
- `engine.js` does no rounding. Rounding lives at the display layer only.
- `data/engine-fixture.json` is regenerated only with `python3 freeze_fixture.py`, and only for a deliberate model change — never to make a failing check pass.
- Every task ends with `python3 test_build.py` green and `python3 build.py --check` clean.

---

### Task 1: The mechanism, shipped neutral

Ships the multiplier with the ratio defaulting to 1.0. Nothing about any vehicle's cost changes. That is the point: it isolates the plumbing from the modelling, and it proves the oracle neutralisation works before anything depends on it.

**Files:**

- Modify: `data/inputs.json` (add one key)
- Modify: `engine.js:24-91` (new `repairMultiplier`, one changed term in `costPerMile`, one new export)
- Modify: `build.py:27` (`REQUIRED_ENGINE_FIELDS`), plus new `oracle_inputs` / `inputs_by_variant` near `dump_variants:293`
- Modify: `freeze_fixture.py:43-59` (`NODE_GENERATOR`), `freeze_fixture.py:89` (payload)
- Modify: `test_engine.mjs:65-88` (per-variant inputs, exact-equality rule), `:112` (published figures), `:143` (winner and frontier)
- Regenerate: `data/engine-fixture.json`

**Interfaces:**

- Produces: `VA.repairMultiplier(v, inp) -> number`, exported alongside `repairReserve`. `build.oracle_inputs(inp) -> dict`, `build.inputs_by_variant(inp) -> {'full': dict, 'workbook_oracle': dict}`.
- Consumes: nothing from earlier tasks.

- [ ] **Step 1: Write the failing test — the multiplier's three known points**

Add to the end of `test_engine.mjs`:

```js
/* The multiplier's shape, pinned at three points. Neutral is 1, not 0:
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
```

- [ ] **Step 2: Run it and watch it fail**

Run: `node test_engine.mjs` — this needs `build-models.json`, which only `test_build.py` writes, so run the suite instead:

```bash
python3 test_build.py
```

Expected: FAIL with `VA.repairMultiplier is not a function`.

- [ ] **Step 3: Add the multiplier to `engine.js`**

Insert after `repairReserve` (which ends at `engine.js:35`), leaving `repairReserve`'s signature alone:

```js
  function repairMultiplier(v, inp) {
    /* Geometric around reliability 50, with the exponent over the full
       0-100 scale, so inp.repair_cost_spread_ratio IS the worst-to-best
       ratio -- there is no second constant to keep in sync with it.

       Neutral is 1, not 0. Math.pow(0, x) returns 0 or Infinity and takes
       every cost per mile with it, which is worth stating because every
       other assumption in this model turns off at zero.

       Anchored at reliability 50 rather than at the fleet's median, because
       costPerMile sees one vehicle at a time: a fleet-relative anchor would
       move every vehicle's cost whenever a row is added. */
    return Math.pow(inp.repair_cost_spread_ratio, (50 - v.reliability) / 100);
  }
```

Change the reserve term in `costPerMile` (currently `engine.js:87`) from:

```js
         + repairReserve(inp)
```

to:

```js
         + repairReserve(inp) * repairMultiplier(v, inp)
```

Add it to the return block at the bottom of the module:

```js
    repairReserve: repairReserve,
    repairMultiplier: repairMultiplier,
```

- [ ] **Step 4: Add the input at its neutral default**

In `data/inputs.json`, after the `repair_reserve_per_mile` block:

```json
  "repair_cost_spread_ratio": 1.0,
```

Neutral for now. Task 2 raises it to 2.66 as its own reviewable change.

- [ ] **Step 5: Assert the field actually reaches the page**

In `build.py:27`, add `reliability` to the tuple. Without this, a missing field is a silent `NaN` in the browser rather than an error:

```python
REQUIRED_ENGINE_FIELDS = ('price', 'mpg', 'fuel', 'deprec5yr', 'tireClass',
                          'observedPrice', 'observedAt', 'reliability')
```

- [ ] **Step 6: Give the oracle its own inputs**

In `build.py`, above `dump_variants` (currently line 293):

```python
# The workbook has no reliability term, so its published figures were
# computed with no spread at all. Neutral for a ratio is 1, not 0.
NEUTRAL_SPREAD = 1.0


def oracle_inputs(inp):
    """Inputs as the workbook computed them.

    Same idea as strip_for_oracle(), one level up: that function removes the
    prices the workbook never saw, this one removes the term it never had.
    Without it the workbook's 11 published figures, its balanced-six winner,
    and its frontier would all have to be rewritten to match a formula the
    spreadsheet does not implement -- which would destroy the only oracle in
    this repo not written by this codebase rather than update it.
    """
    return dict(inp, repair_cost_spread_ratio=NEUTRAL_SPREAD)


def inputs_by_variant(inp):
    """The inputs each dump_variants() variant must be evaluated under.

    Returned together so the Node consumers -- freeze_fixture.py and
    test_engine.mjs -- cannot pair a variant with the wrong input set.
    """
    return {'full': inp, 'workbook_oracle': oracle_inputs(inp)}
```

- [ ] **Step 7: Freeze each variant under its own inputs**

In `freeze_fixture.py`, change the `NODE_GENERATOR` loop body (line 51) from:

```js
    const cpm = VA.costPerMile(m, payload.inputs);
```

to:

```js
    const cpm = VA.costPerMile(m, payload.inputsByVariant[variant]);
```

and the payload write (line 89) from:

```python
    models_path.write_text(json.dumps({'models': dumped, 'inputs': build.INPUTS}))
```

to:

```python
    models_path.write_text(json.dumps({
        'models': dumped,
        'inputsByVariant': build.inputs_by_variant(build.INPUTS)}))
```

`_inputs` in the fixture stays the live full input set — `check_js_engine_parity`'s drift check compares it against `build.INPUTS`, and that comparison must keep meaning what it means.

- [ ] **Step 8: Route the JS oracle through the neutral inputs**

In `test_engine.mjs`, after `const inputs = fixture._inputs;` (line 15):

```js
/* The workbook has no reliability term. Every assertion below that derives
   from the spreadsheet -- the frozen oracle variant, the 11 published
   figures, the balanced-six winner, the frontier -- runs at a neutral
   spread, mirroring build.oracle_inputs() on the Python side. */
const ORACLE_INPUTS = { ...inputs, repair_cost_spread_ratio: 1 };
const INPUTS_FOR = { full: inputs, workbook_oracle: ORACLE_INPUTS };
```

In the parity loop, change line 78 from `VA.costPerMile(v, inputs)` to:

```js
    const got = VA.costPerMile(v, INPUTS_FOR[variant]);
```

and tighten the tolerance for the neutral variant, right after the `delta` is computed:

```js
    /* The oracle variant is frozen at a neutral spread, and multiplying by
       exactly 1.0 is exact in IEEE-754. So this variant must match to the
       bit, not to a tolerance -- any drift at all means the multiplier is
       not neutral at 1 and every workbook assertion below is running
       against a formula the spreadsheet never implemented. */
    if (variant === 'workbook_oracle' && delta !== 0) {
      throw new Error(`${v.name}: neutral spread moved the figure by ${delta} -- `
        + `it must be bit-for-bit identical`);
    }
```

Change the published-figures call (line 112) to:

```js
  const got = VA.costPerMile({ ...m, observedPrice: null }, ORACLE_INPUTS);
```

Change the winner and frontier call (line 143) to:

```js
const cpms = models.map(m => VA.costPerMile(m, ORACLE_INPUTS));
```

- [ ] **Step 9: Regenerate the fixture and confirm no number moved**

```bash
python3 freeze_fixture.py
git diff --stat data/engine-fixture.json
git diff data/engine-fixture.json | grep -c '"cpm"'
```

Expected: the second command reports `0`. The only change in the file is `_inputs` gaining `repair_cost_spread_ratio`. A nonzero count means the multiplier is not neutral at 1.0 and Step 3 is wrong — fix the engine, do not accept the new numbers.

- [ ] **Step 10: Run everything**

```bash
python3 test_build.py && python3 build.py --check
```

Expected: all green, including `ok: 11 published $/mile figures match` and the new multiplier line.

- [ ] **Step 11: Commit**

```bash
git add engine.js build.py freeze_fixture.py test_engine.mjs data/inputs.json data/engine-fixture.json
git commit -F- <<'EOF'
Add the reliability multiplier, shipped neutral

The reserve is now scaled by ratio^((50 - reliability)/100), with the ratio
defaulting to 1.0 so no vehicle's cost changes yet. Neutral for a ratio is 1,
not 0, and multiplying by exactly 1.0 is exact in IEEE-754 -- the regenerated
fixture carries byte-identical cpm figures, which is the proof.

The workbook oracle runs at the neutral ratio across its whole path, not just
the 11 published figures: the balanced-six winner and the frontier are
workbook-derived too, and rewriting their expectations would destroy the only
check in this repo that this codebase did not write.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
```

---

### Task 2: Turn it on

**Files:**

- Modify: `data/inputs.json` (one value)
- Regenerate: `data/engine-fixture.json`

**Interfaces:**

- Consumes: `repair_cost_spread_ratio` from Task 1.
- Produces: the shipped default the page and the export both read.

- [ ] **Step 1: Record the ranking before the change**

Writes its scratch files to `/tmp`, never into the repo — an interrupted run must not leave untracked junk in a tree that gets committed from.

```bash
python3 - <<'EOF' > /tmp/ranking-before.txt
import json, subprocess, shutil, pathlib, build
rows = build.load()
models = build.build_models(rows, build.INPUTS)
tmp = pathlib.Path('/tmp')
(tmp / 'rank-models.json').write_text(json.dumps({'models': models, 'inputs': build.INPUTS}))
(tmp / 'rank.js').write_text('''
const {readFileSync} = require('fs');
const VA = require(process.argv[2]);
const p = JSON.parse(readFileSync('/tmp/rank-models.json', 'utf8'));
const out = p.models.map(m => [VA.costPerMile(m, p.inputs), m.name]);
out.sort((a, b) => a[0] - b[0]);
out.forEach(([c, n], i) => console.log(`${String(i + 1).padStart(2)} ${c.toFixed(4)} ${n}`));
''')
engine = str(pathlib.Path('engine.js').resolve())
print(subprocess.run([shutil.which('node'), '/tmp/rank.js', engine],
                     capture_output=True, text=True).stdout)
EOF
git status --short   # must show nothing new
```

- [ ] **Step 2: Set the default**

In `data/inputs.json`:

```json
  "repair_cost_spread_ratio": 2.66,
```

- [ ] **Step 3: Regenerate the fixture**

```bash
python3 freeze_fixture.py
```

This is a deliberate model change, which is exactly the case the fixture's own comment sanctions.

- [ ] **Step 4: Confirm the oracle did NOT move**

```bash
git diff data/engine-fixture.json | grep '"cpm"' | wc -l
```

Expected: 79 changed lines, all inside the `full` block. If any `workbook_oracle` cpm changed, the neutralisation from Task 1 is broken — stop and fix that before continuing.

- [ ] **Step 5: Run everything**

```bash
python3 test_build.py && python3 build.py --check
```

Expected: green. `ok: 11 published $/mile figures match` must still pass; those figures are the workbook's and must be untouched by this change.

- [ ] **Step 6: Record the ranking after, and diff it**

Re-run Step 1's script into `/tmp/ranking-after.txt`, then:

```bash
diff /tmp/ranking-before.txt /tmp/ranking-after.txt | head -40
```

Keep the output. It goes in the PR body, so the ranking change is visible rather than asserted.

- [ ] **Step 7: Commit**

`index.html` is in this list because `build.py` inlines `INPUTS` into it. Leaving it out fails `check_page_up_to_date`.

```bash
git add data/inputs.json data/engine-fixture.json index.html
git commit -F- <<'EOF'
Set the reliability spread to the published 2.66x

RepairPal's 2026 brand averages put Toyota at $441/yr and Land Rover at
$1,174/yr, a 2.66x worst-to-best spread. Across this fleet's actual
reliability range (17.4 to 100) that applies a 2.24x spread, moving the
reserve from $0.034 to $0.077 per mile -- about $2,337 a year at 55,000
miles.

The workbook oracle is untouched: it runs at a neutral ratio, so all 11
published figures still match.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
```

---

### Task 3: Say so on the page

**Files:**

- Modify: `index.html` — `AXES` (line ~310), the notes fine print (line ~157), `buildExport`'s fixed-assumption block
- Modify: `test_export.mjs` — the required-label list

**Interfaces:**

- Consumes: `repair_cost_spread_ratio` from Task 1, `INPUTS` as already inlined by `build.py`.
- Produces: the export label `Repair cost spread, worst/best`.

- [ ] **Step 1: Write the failing test**

In `test_export.mjs`, add to the existing required-label loop:

```js
for (const label of ['Repair reserve $/mi, over 150k', 'Sales tax rate', 'Loan APR',
  'Industry average 5-year depreciation', 'Cash opportunity rate',
  'Repair cost spread, worst/best']) {
```

and add the key to the test's `INPUTS` fixture near the top:

```js
  sales_tax_rate: 0.07, industry_avg_5yr_deprec: 0.418, repair_cost_spread_ratio: 2.66,
```

- [ ] **Step 2: Run it and watch it fail**

```bash
node test_export.mjs
```

Expected: FAIL with `export is missing the Repair cost spread, worst/best assumption`.

- [ ] **Step 3: Add it to the export**

In `index.html`, inside `buildExport`'s fixed-assumption array, after the three repair-reserve band rows:

```js
   ["Repair cost spread, worst/best",INPUTS.repair_cost_spread_ratio],
```

- [ ] **Step 4: Run it and watch it pass**

```bash
node test_export.mjs
```

Expected: `ok: export carries 30 vehicles across 27 columns, assumptions intact`.

- [ ] **Step 5: Retag the Cost axis**

In `index.html`'s `AXES`, change the Cost and Reliability entries to:

```js
 ["Cost","computed + judgment","Cost per mile; repair reserve scaled by the reliability guess"],
```

```js
 ["Reliability","SWAG","Time in the shop, not dollars -- the dollars are in Cost"],
```

- [ ] **Step 6: Correct the notes fine print**

In `index.html`'s `.fine` paragraph, replace:

```html
      <strong>Cost</strong> is computed from the workbook.
```

with:

```html
      <strong>Cost</strong> is computed from the workbook, with one judgment in it: the
      repair reserve is scaled by each vehicle's reliability score, so the least reliable
      row carries about 2.2x the reserve of the most reliable. Reliability therefore
      reaches the chart twice — as dollars here, and as time in the shop on its own axis.
```

- [ ] **Step 7: Run everything**

```bash
python3 test_build.py && python3 build.py --check
```

Expected: green. `build.py --check` must stay clean, which proves these edits landed outside the block `build.py` regenerates.

- [ ] **Step 8: Commit**

```bash
git add index.html test_export.mjs
git commit -F- <<'EOF'
Tag the Cost axis as carrying a judgment, and export the spread

Cost was the one axis the README called trustworthy. It now has a SWAG inside
it, so the slider says so where people read the number rather than only in the
README. The reliability slider is retitled to what it still measures on its
own axis: time in the shop, not dollars.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
```

---

### Task 4: README

**Files:**

- Modify: `README.md` — the axis-trust section and "Before trusting any of it"

**Interfaces:**

- Consumes: the behaviour shipped in Tasks 1-3.

- [ ] **Step 1: Correct the axis-trust bullet**

Replace:

```markdown
- **Cost** is computed from the workbook.
```

with:

```markdown
- **Cost** is computed from the workbook, with one judgment inside it: the repair reserve is scaled by each vehicle's reliability score, `ratio^((50 - reliability)/100)`, where the ratio defaults to 2.66 — the worst-to-best spread in RepairPal's 2026 brand repair-cost averages (Toyota $441/yr, Land Rover $1,174/yr). Set `repair_cost_spread_ratio` to 1 in `data/inputs.json` to turn it off; the neutral value is 1, not 0.
```

- [ ] **Step 2: Correct the maintenance claim in "Adjusting the assumptions"**

The section currently says the three "Budget only" fields cannot change which vehicle wins. Maintenance per mile still cannot, but the sentence names the repair reserve elsewhere in the file. Replace the paragraph beginning "The remaining three, labelled" with:

```markdown
The remaining three, labelled "Budget only", are maintenance per mile, insurance, and registration. Those are identical for every vehicle, so they shift all 79 costs per mile by the same constant. They change what the vehicle costs you; they cannot change which one wins. The repair reserve used to work the same way and no longer does — see the Cost bullet under "The six axes are not equally trustworthy".
```

- [ ] **Step 3: Add the honesty note to "Before trusting any of it"**

Add as a new bullet:

```markdown
- **A guess now moves the dollars.** Reliability is one of the two axes this README calls an informed guess, and it scales the repair reserve, so the Cost axis is no longer purely computed. The spread's width is sourced; which vehicle sits where on the reliability scale is not. NHTSA complaint and TSB data and the UK DVSA MOT results are the path to replacing that guess with something measured.
```

- [ ] **Step 4: Run everything**

```bash
python3 test_build.py && python3 build.py --check
```

Expected: green. `check_readme_counts` asserts two statistics in this file; neither is touched by these edits, and a failure there means a number was disturbed by accident.

- [ ] **Step 5: Commit**

```bash
git add README.md
git commit -F- <<'EOF'
Document the judgment now sitting inside the Cost axis

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
```

---

## Verification before the PR

- [ ] `python3 test_build.py` green, including `ok: 11 published $/mile figures match`
- [ ] `python3 build.py --check` clean
- [ ] `git diff main --stat` touches only the files in the four touch lists
- [ ] The ranking diff from Task 2, Step 6 is pasted into the PR body
- [ ] PR opened against `main`, then reviewed with `codex-review`, iterated to approve
