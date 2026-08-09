# Trim Migration Implementation Plan (Plan A)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the codebase able to hold per-trim rows, and guard the currency errors that sourcing ~700 prices will invite, without changing a single vehicle number.

**Architecture:** Three independent changes. A plausibility gate on prices. A row key that becomes `(nameplate, trim)` everywhere a nameplate is used as a map key today. A chart that collapses a nameplate's trims into one point until selected. None of them touches vehicle data, so the whole plan is verifiable against the numbers already on the page.

**Tech Stack:** Python 3.8+ stdlib, plain ES5 JavaScript, Node 20+ (tests only).

## Global Constraints

- **No vehicle number may change.** The acceptance criterion for this plan is that the published page renders identical figures. The 158-comparison engine parity gate is the control.
- **`data/engine-fixture.json` is re-keyed, never recomputed.** Its values are the frozen output of the deleted Python engine and are the only ground truth not produced by the current code. A mechanical key transform preserves that; a regeneration destroys it. Never run `freeze_fixture.py` in this plan.
- `index.html` stays **ES5**: `var` and `function` only, no `const` beyond the grandfathered `const MODELS`, no `let`, no arrows, no template literals, no spread.
- No rounding inside `engine.js`; round only at display.
- `python3 test_build.py` remains the single test entry point.
- Every monetary figure is **USD**.
- Never restore `data/vehicles.csv` with a Python read/write round-trip. It is CRLF and a naive round-trip converts all 80 lines to LF. Use `git checkout --`.

---

### Task 1: Currency and plausibility gate

Closes #24. Ships first because it guards every price added afterwards, and because its category ceiling is what catches the `$60,585` CAD Honda CR-V that a search returned during the 90k-tier sourcing. The global bound alone does not.

**Files:**

- Modify: `build.py` (`price_problems`, plus a `PRICE_BOUNDS` constant)
- Modify: `data/inputs.json` (state the currency)
- Modify: `README.md`
- Test: `test_build.py` (`check_price_resolution`)

**Interfaces:**

- Consumes: nothing from earlier tasks.
- Produces: `build.PRICE_BOUNDS`, a `(min, max)` tuple of USD; `price_problems` gains plausibility rejection.

- [ ] **Step 1: Write the failing rejection cases**

Add to the `rejected` list in `check_price_resolution` in `test_build.py`:

```python
        # Plausibility. The CAD figure that prompted this was $60,585 for a
        # CR-V Hybrid whose real US price is nearer $35-40k, so the bound has
        # to be wide enough for a real Escalade and tight enough to catch a
        # currency error on a mainstream crossover.
        dict(name='k', observed_price='400000', price_year='2023',
             price_source='x', observed_price_odometer='40000'),   # too high
        dict(name='l', observed_price='250', price_year='2023',
             price_source='x', observed_price_odometer='40000'),   # too low
        dict(name='m', price='0'),                                 # zero placeholder
```

- [ ] **Step 2: Run it and watch it fail**

Run: `python3 test_build.py`
Expected: FAIL with `gate accepted a bad row: {'name': 'k', ...}`

- [ ] **Step 3: Implement the gate**

In `build.py`, after `REQUIRED_ENGINE_FIELDS`:

```python
# Every monetary figure in this project is USD. These bounds are a data-entry
# check, not a currency detector: a passenger vehicle outside this range is an
# error of units or of decimal point. The case that motivated it was a search
# returning $60,585 for a Honda CR-V Hybrid -- a Canadian dealer quoting CAD,
# roughly 35% high, caught only because it looked wrong beside its siblings.
PRICE_BOUNDS = (5000, 250000)

# A global bound alone would NOT have caught the case that motivated this:
# $60,585 sits comfortably inside it. Category ceilings do -- compact
# crossovers in this dataset span $19,000-$30,000, so a CAD figure at double
# the ceiling is unmistakable. The multiplier is deliberately loose: this is
# a data-entry check, not a pricing model, and a real outlier should survive.
CATEGORY_HEADROOM = 2.0
```

In `price_problems`, inside the loop, after the provenance checks:

```python
        for field in ('price', 'observed_price', 'msrp', 'mix_price'):
            raw = str(v.get(field, '')).strip()
            if raw == '':
                continue
            try:
                amount = float(raw)
            except ValueError:
                problems.append(f'{name}: {field} is not a number: {raw!r}')
                continue
            lo, hi = PRICE_BOUNDS
            cap = category_ceiling(rows, v.get('category'))
            if cap and amount > cap * CATEGORY_HEADROOM:
                problems.append(
                    f'{name}: {field} of ${amount:,.0f} is more than '
                    f'{CATEGORY_HEADROOM:g}x the highest {v["category"]} price '
                    f'(${cap:,.0f}). All figures are USD; check for a '
                    f'foreign-currency error')
            if not lo <= amount <= hi:
                problems.append(
                    f'{name}: {field} of ${amount:,.0f} is outside the plausible '
                    f'USD range ${lo:,}-${hi:,}. All figures in this project are '
                    f'USD; check for a foreign-currency or decimal-point error')
```

- [ ] **Step 4: Run the tests**

Run: `python3 build.py --check && python3 test_build.py`
Expected: PASS. Every existing price is inside the bounds, so nothing changes.

- [ ] **Step 5: Prove it fires on real data**

```bash
python3 - <<'PY'
import csv, pathlib, subprocess
p = pathlib.Path('data/vehicles.csv'); orig = p.read_bytes()
rows = list(csv.DictReader(open(p)))
# Simulate the CAD error on a real row, writing CRLF as csv.DictWriter does.
for r in rows:
    if r['name'] == 'Honda CR-V Hybrid':
        r['price'] = '60585'
with open(p, 'w', newline='') as fh:
    w = csv.DictWriter(fh, fieldnames=rows[0].keys()); w.writeheader(); w.writerows(rows)
r = subprocess.run(['python3', 'build.py'], capture_output=True, text=True)
p.write_bytes(orig)
print(f'CAD price -> exit {r.returncode}')
print((r.stderr.strip().splitlines() or ['(none)'])[-1][:140])
assert r.returncode != 0, 'the plausibility gate did not fire'
PY
```

The global bound alone would **not** catch this: `$60,585` sits inside `5000-250000`. The category ceiling is what catches it — compact crossovers in this dataset top out at `$30,000`, so a figure at double that is rejected. Confirm the failure message names the category comparison rather than the global range, and record in the report which of the two fired.

- [ ] **Step 6: Document and commit**

Add to `data/inputs.json` a `"_currency": "USD"` key beside `_comment`. Add one line to the README's price section stating every figure is USD. Then:

```bash
git add build.py test_build.py data/inputs.json README.md index.html
git commit -m "feat: reject implausible prices, and state the currency

Closes #24. Every monetary figure in this project is USD and nothing said so
or checked. Sourcing trim prices across 79 nameplates multiplies the exposure
that already produced a \$60,585 CAD figure for a Honda CR-V Hybrid.

A global bound alone would not have caught it: \$60,585 sits inside
\$5,000-\$250,000. The category ceiling does -- compact crossovers top out at
\$30,000 here, so double that is unmistakable. A guard that misses the error
that prompted it is decorative."
```

---

### Task 2: Row key becomes (nameplate, trim)

**Files:**

- Modify: `data/vehicles.csv` (add `trim`, `trim_name`)
- Modify: `build.py` (`row_key`, `load`, `build_models`, `price_problems`)
- Modify: `test_engine.mjs` (fixture lookup, `PUBLISHED`, frontier)
- Modify: `data/engine-fixture.json` (**re-keyed, not recomputed**)
- Test: `test_build.py`

**Interfaces:**

- Consumes: `build.PRICE_BOUNDS` from Task 1.
- Produces: `build.row_key(row)` returning `f"{name}|{trim}"`; every emitted model gains `key` (the map key) and `trimName` (the display badge); `trim` defaults to `unspecified` for rows without one.

- [ ] **Step 1: Add the columns, defaulted**

```bash
python3 - <<'PY'
import csv, pathlib
p = pathlib.Path('data/vehicles.csv')
rows = list(csv.DictReader(open(p)))
cols = list(rows[0].keys())
for c in ('trim', 'trim_name'):
    if c not in cols:
        cols.insert(cols.index('name') + 1, c)
for r in rows:
    # 'unspecified' is the honest pre-trim state. These rows are neither base
    # nor volume nor loaded -- the placeholders are base-ish estimates and the
    # four observed prices are market-mix averages. Plan B assigns real tiers.
    r.setdefault('trim', 'unspecified')
    r.setdefault('trim_name', '')
with open(p, 'w', newline='') as fh:
    w = csv.DictWriter(fh, fieldnames=cols); w.writeheader(); w.writerows(rows)
print(f'{len(rows)} rows defaulted to trim=unspecified')
PY
```

Expected: `79 rows defaulted to trim=unspecified`

- [ ] **Step 2: Write the failing key tests**

Add to `test_build.py`, called from `main()` after `check_emitted_schema(real)`:

```python
def check_row_keys(rows):
    """Row identity is (nameplate, trim), and it must be unique.

    Every map keyed by bare name -- the engine fixture, the recall cache, the
    workbook assertions -- collides the moment one nameplate appears twice.
    """
    seen = {}
    for v in rows:
        key = build.row_key(v)
        assert key not in seen, f'duplicate row key {key!r}'
        seen[key] = v
    assert len(seen) == len(rows)

    # Tiers are only meaningful once a nameplate has more than one row. Until
    # then 'unspecified' is correct and must not be mistaken for a real tier.
    valid = {'base', 'volume', 'loaded', 'unspecified'}
    for v in rows:
        assert v['trim'] in valid, f'{v["name"]}: unknown trim {v["trim"]!r}'

    # Partial population is the failure mode: one trim assigned and the rest
    # left unspecified would silently compare a tier against a non-tier.
    by_plate = {}
    for v in rows:
        by_plate.setdefault(v['name'], []).append(v['trim'])
    for plate, trims in by_plate.items():
        real = [t for t in trims if t != 'unspecified']
        assert not real or len(real) == len(trims), \
            f'{plate}: partially assigned trims {trims}'
```

- [ ] **Step 3: Run and watch it fail**

Run: `python3 test_build.py`
Expected: FAIL with `AttributeError: module 'build' has no attribute 'row_key'`

- [ ] **Step 4: Implement the key**

In `build.py`, after `PRICE_BOUNDS`:

```python
def category_ceiling(rows, category):
    """Highest placeholder price in a category, or None if it is the only row.

    Used only as a sanity ceiling. Reads `price` rather than the resolved buy
    price so the bound does not move as observed prices are added.
    """
    peers = [float(r['price']) for r in rows
             if r.get('category') == category and str(r.get('price', '')).strip()]
    return max(peers) if len(peers) > 1 else None


def row_key(v):
    """Stable identity for a row: nameplate plus trim.

    Used as the key in data/engine-fixture.json and in the workbook
    assertions. A bare nameplate stops being unique as soon as one vehicle
    carries more than one trim.
    """
    return f"{v['name']}|{v.get('trim') or 'unspecified'}"
```

In `build_models`, add to the emitted dict beside `'name'`:

```python
            'key': row_key(v),
            'trimName': v.get('trim_name') or '',
```

In `price_problems`, add:

```python
        if v.get('trim') not in ('base', 'volume', 'loaded', 'unspecified'):
            problems.append(f'{name}: trim must be base, volume, loaded, or '
                            f'unspecified; got {v.get("trim")!r}')
        if v.get('trim') in ('base', 'volume', 'loaded') and not v.get('trim_name'):
            problems.append(f'{name}: trim {v["trim"]!r} without trim_name -- '
                            f'a tier needs the badge a reader would recognise')
```

- [ ] **Step 5: Re-key the fixture without recomputing it**

**This is the step that must not be done with `freeze_fixture.py`.** The fixture holds the frozen output of the deleted Python engine and is the only ground truth this codebase did not produce. Transform its keys; preserve every value.

```bash
python3 - <<'PY'
import json, pathlib
import build
p = pathlib.Path('data/engine-fixture.json')
fx = json.loads(p.read_text())
rows = {r['name']: r for r in build.load()}
before = {v: dict(fx[v]) for v in ('full', 'workbook_oracle')}
for variant in ('full', 'workbook_oracle'):
    fx[variant] = {build.row_key(rows[name]): val
                   for name, val in fx[variant].items()}
fx['_comment'] += (' Keys are (nameplate|trim) as of the trim migration; '
                   'values are unchanged from the original freeze.')
p.write_text(json.dumps(fx, indent=2, sort_keys=True) + '\n')
# Values must be identical -- only keys moved.
for variant in ('full', 'workbook_oracle'):
    old = sorted(json.dumps(v, sort_keys=True) for v in before[variant].values())
    new = sorted(json.dumps(v, sort_keys=True) for v in fx[variant].values())
    assert old == new, f'{variant}: VALUES CHANGED -- this must be a key transform only'
print('fixture re-keyed; all 158 values byte-identical')
PY
```

Expected: `fixture re-keyed; all 158 values byte-identical`

- [ ] **Step 6: Point the Node harness at the new key**

In `test_engine.mjs`, replace `v.name` with `v.key` in the fixture lookup and in `assertVariantShape`'s name set. Change `PUBLISHED` keys to the `nameplate|unspecified` form, and `EXPECTED_FRONTIER` likewise. Leave the values alone.

- [ ] **Step 7: Run everything**

Run: `python3 build.py && python3 test_build.py`
Expected: PASS with `158 comparisons within 1e-12` unchanged, and every downstream assertion green.

Then confirm no vehicle number moved:

```bash
python3 - <<'PY'
import json, re, subprocess
def models(src):
    return {m['name']: m for m in json.loads(
        re.search(r'const MODELS = (\[.*?\]);', src, re.S).group(1))}
old = models(subprocess.run(['git', 'show', 'HEAD:index.html'],
                            capture_output=True, text=True).stdout)
new = models(open('index.html').read())
assert set(old) == set(new), 'vehicle set changed'
for n, o in old.items():
    for k in ('price', 'mpg', 'quality', 'longevity', 'reliability',
              'comfort', 'efficiency', 'tier'):
        assert o[k] == new[n][k], f'{n}.{k}: {o[k]} -> {new[n][k]}'
print(f'{len(new)} vehicles: every figure identical')
PY
```

- [ ] **Step 8: Commit**

```bash
git add data/vehicles.csv data/engine-fixture.json build.py test_build.py test_engine.mjs index.html
git commit -m "refactor: row identity becomes (nameplate, trim)

Every map keyed by bare nameplate collides the moment one vehicle carries
more than one trim: the engine fixture, the workbook assertions, and the
recall cache.

data/engine-fixture.json is RE-KEYED, not regenerated. Its values are the
frozen output of the deleted Python engine and are the only ground truth this
codebase did not produce; a key transform preserves that, a regeneration
would destroy it. Verified all 158 values byte-identical after the transform.

Existing rows default to trim=unspecified, which is honest: the placeholders
are base-ish estimates and the four observed prices are market-mix averages,
so neither is a tier. Partial assignment within a nameplate is rejected."
```

---

### Task 3: Collapse a nameplate's trims into one chart point

Closes #12. Nothing has multiple trims yet, so this is built and tested against synthetic duplicates before the data arrives.

**Files:**

- Modify: `index.html` (`compute`, `drawChart`, `drawRanked`)

**Interfaces:**

- Consumes: `m.key`, `m.name`, `m.trimName` from Task 2.
- Produces: `collapseByNameplate(scored)`, returning one representative per nameplate plus the trims it stands for.

- [ ] **Step 1: Implement the collapse**

In `index.html`, after `compute()` builds `scored`:

```javascript
function collapseByNameplate(list){
  /* One point per nameplate until it is selected. 79 nameplates at three
     trims each is 237 near-identical points, and the frontier would fill
     with cross-tier comparisons -- a base Escalade beating a loaded
     Highlander -- which describes nothing anyone shops. */
  var by={}, order=[];
  for(var i=0;i<list.length;i++){
    var m=list[i];
    if(!by[m.name]){by[m.name]={rep:m,trims:[]}; order.push(m.name)}
    by[m.name].trims.push(m);
    /* Represent the nameplate by its best-scoring trim, so collapsing never
       hides a vehicle that would have made the frontier. */
    if(m.total>by[m.name].rep.total)by[m.name].rep=m;
  }
  var out=[];
  for(var j=0;j<order.length;j++){
    var g=by[order[j]], r=g.rep;
    r.trimCount=g.trims.length;
    r.trims=g.trims;
    out.push(r);
  }
  return out;
}
```

Use the collapsed list for the chart and the ranked list. When `SEL` names a nameplate with more than one trim, render that nameplate's trims as individual points instead of its representative.

- [ ] **Step 2: Test against synthetic duplicates**

Nothing in the dataset has trims yet, so prove the behaviour with a temporary third row:

```bash
python3 - <<'PY'
import csv, pathlib, subprocess
p = pathlib.Path('data/vehicles.csv'); orig = p.read_bytes()
rows = list(csv.DictReader(open(p)))
base = next(r for r in rows if r['name'] == 'Toyota Highlander Hybrid')
for tier, badge, price in (('base','XLE','36000'),
                           ('volume','Limited','41000'),
                           ('loaded','Platinum','45000')):
    r = dict(base); r['trim']=tier; r['trim_name']=badge
    r['price']=price; r['observed_price']=''; r['observed_price_odometer']=''
    r['price_year']=''; r['price_source']=''
    rows.append(r)
rows = [r for r in rows if not (r['name']=='Toyota Highlander Hybrid'
                                and r['trim']=='unspecified')]
with open(p,'w',newline='') as fh:
    w=csv.DictWriter(fh,fieldnames=rows[0].keys()); w.writeheader(); w.writerows(rows)
print('built a 3-trim Highlander Hybrid; row count now', len(rows))
PY
```

Then rebuild and confirm in a browser: the chart shows **one** Highlander Hybrid point, the frontier count reflects nameplates rather than rows, and selecting it expands to three points labelled XLE, Limited, and Platinum.

Restore with `git checkout -- data/vehicles.csv` — **not** a Python round-trip, which would convert CRLF to LF.

Note the fixture will not match while the synthetic rows exist; that is expected, and the restore returns it to green.

- [ ] **Step 3: Confirm the default view is unchanged**

Run: `python3 build.py --check && python3 test_build.py`

With every row at `trim=unspecified`, each nameplate has exactly one row, so `collapseByNameplate` is an identity transform and the page must render exactly as before. Confirm the frontier still reads `6 of 79`.

- [ ] **Step 4: Commit**

```bash
git add index.html
git commit -m "feat: collapse a nameplate's trims into one chart point

Closes #12. 79 nameplates at three trims is 237 near-identical clustered
points, and the frontier would fill with cross-tier comparisons that
describe nothing anyone shops.

A nameplate renders as its best-scoring trim until selected, so collapsing
never hides a vehicle that would have made the frontier, then expands to its
trims on selection. With every row currently at trim=unspecified this is an
identity transform and the page is unchanged."
```

---

## Self-review

**Spec coverage.** This plan covers the spec's sequencing steps 1 (currency gate), 2 (row-key migration), and 3 (chart collapse). Steps 4 through 6 — the schema columns populated with real tier data, per-trim comfort closing #20, and the remaining nameplates — are Plan B, written once this lands and once the sourcing yield is known.

**Placeholders.** None. Every step carries its code or command.

**Type consistency.** `build.row_key(v)` returns a string in Task 2 and is consumed as a fixture key in Task 2 Step 5 and in `test_engine.mjs` Step 6. `m.key`, `m.name`, `m.trimName`, and `m.total` are the fields `collapseByNameplate` reads in Task 3, and all four are emitted or computed before it runs.

**Self-review changed Task 1.** The first draft used only a global `5000-250000` bound and deferred per-category bounds to a follow-up. Checking the data showed that would ship a gate missing its own motivating case: `$60,585` is inside the global range, while compact crossovers top out at `$30,000`. The category ceiling is now in Task 1, because a guard that does not catch the error that prompted it is decorative.

**Deliberate deviation from the spec.** The spec says the fixture is "regenerated deliberately and the diff inspected". This plan **re-keys it instead**, because a mechanical key transform preserves the frozen Python values that are the only ground truth this codebase did not produce. Regeneration would replace an independent witness with the current engine's own output. The spec's intent — a deliberate, inspected change rather than a silent one — is met more strongly by a transform whose values are asserted byte-identical.
