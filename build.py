#!/usr/bin/env python3
"""Generate the MODELS array in index.html from data/vehicles.csv.

The CSV holds only observations and judgments. Cost per mile and the 0-100
cost axis are computed in the browser now, by engine.js -- this module still
derives the 0-100 efficiency axis, so adding a row means adding a row, not
hand-recomputing that column too.

    python3 build.py           rewrite index.html in place
    python3 build.py --check   verify index.html is up to date (exit 1 if not)

Mirrors the Models tab of vehicle-turnover-planner.xlsx. Sources for every
assumption are on that workbook's Sources tab.
"""
import argparse
import csv
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).parent
INPUTS = json.loads((ROOT / 'data' / 'inputs.json').read_text())
MARKER = 'const MODELS = '

# Fields engine.js reads. Absence is a NaN in the browser, not an exception,
# so test_build.py asserts every one of these reaches the page.
REQUIRED_ENGINE_FIELDS = ('price', 'mpg', 'fuel', 'deprec5yr', 'tireClass',
                          'observedPrice', 'observedAt', 'reliability')

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


def row_key(v):
    """Stable identity for a row: nameplate plus trim.

    Used as the key in data/engine-fixture.json and in the workbook
    assertions. A bare nameplate stops being unique as soon as one vehicle
    carries more than one trim.
    """
    return f"{v['name']}|{v.get('trim') or 'unspecified'}"


def buy_price(v, inp):
    """Price at the buy odometer, and the basis it came from.

    Observed market listings only. MSRP-through-the-curve was tried and
    retired: resale_multiplier is built from FIVE-year depreciation but the buy
    point is a ~3-year-old vehicle, so fast-depreciating models get penalised
    twice. It put the 2023 Escalade at $50,941 against an observed $70,777
    across three listing services -- worse than the placeholder it replaced.

    msrp/msrp_year/msrp_trim are kept as reference only. They record what a
    vehicle costs new; they no longer compute what a used one costs.
    """
    if v.get('observed_price'):
        return float(v['observed_price']), 'observed'
    return float(v['price']), 'placeholder'


def category_ceiling(rows, category, exclude):
    """Highest placeholder price among a category's rows from OTHER
    nameplates, or None if none remain.

    Used only as a sanity ceiling. Reads `price` rather than the resolved buy
    price so the bound does not move as observed prices are added.

    Excludes every row that shares `exclude`'s nameplate, not just `exclude`
    itself. Excluding only the row under test was tried first and does not
    work for sibling trims: sourcing all of a nameplate's trims from one bad
    page gives that nameplate several inflated rows, and each becomes the
    other's ceiling -- `amount > cap * CATEGORY_HEADROOM` can never fire for
    any of them because their mutual peer is inflated by the same amount.
    Excluding the whole nameplate closes that gap. It does NOT close the
    parallel one: two DIFFERENT nameplates that are both wrong in the same
    category at the same time still vouch for each other, since neither is
    excluded from the other's peer set. That is a real, unclosed gap --
    recorded here honestly rather than implying this check is stronger than
    it is. Singletons still resolve to None here: a nameplate that is the
    only member of its category (or whose siblings are its only
    categorymates) has no peers regardless of how many trims it carries.

    Peers whose `price` does not parse as a float are skipped rather than
    raising. Those peers have not been validated yet -- price_problems calls
    this once per row in an unspecified order -- so a malformed price on one
    row must not raise while computing the ceiling for a *different* row.
    The malformed row is reported on its own iteration by the per-row check
    below.
    """
    peers = []
    for r in rows:
        if r.get('category') != category or r.get('name') == exclude.get('name'):
            continue
        raw = str(r.get('price', '')).strip()
        if not raw:
            continue
        try:
            peers.append(float(raw))
        except ValueError:
            continue
    return max(peers) if peers else None


def price_problems(rows):
    """Data-integrity checks on price provenance and row identity. Empty
    list means clean.

    Unknown provenance has to be an error rather than a silent default, or the
    check is decorative -- a placeholder that nobody flags reads exactly like a
    verified figure once it reaches the page. Row identity is held to the
    same standard: build.py is what the README tells a data contributor to
    run, so the (nameplate, trim) invariants must be enforced here, not only
    asserted in a test that never runs against a contributor's edit.

    Uniqueness and partial-trim-assignment are properties of the whole set,
    not of any one row, so they are checked once up front rather than inside
    the per-row loop below.
    """
    problems = []

    # Row identity: (nameplate, trim) must be unique, or every map keyed by
    # row_key -- the engine fixture, the recall cache, the workbook
    # assertions -- collides the moment two rows share it.
    seen = set()
    for v in rows:
        key = row_key(v)
        if key in seen:
            problems.append(f'duplicate row key {key!r}')
        else:
            seen.add(key)

    # Partial trim assignment is the failure mode: one trim assigned and the
    # rest left unspecified would silently compare a tier against a
    # non-tier. A nameplate's trims must be either all real tiers or all
    # unspecified.
    by_plate = {}
    for v in rows:
        by_plate.setdefault(v['name'], []).append(v.get('trim'))
    for plate, trims in by_plate.items():
        real = [t for t in trims if t != 'unspecified']
        if real and len(real) != len(trims):
            problems.append(f'{plate}: partially assigned trims {trims}')

    for v in rows:
        name = v['name']
        if v.get('trim') not in ('base', 'volume', 'loaded', 'unspecified'):
            problems.append(f'{name}: trim must be base, volume, loaded, or '
                            f'unspecified; got {v.get("trim")!r}')
        if v.get('trim') in ('base', 'volume', 'loaded') and not v.get('trim_name'):
            problems.append(f'{name}: trim {v["trim"]!r} without trim_name -- '
                            f'a tier needs the badge a reader would recognise')
        if v.get('observed_price'):
            if not v.get('price_year'):
                problems.append(f'{name}: observed_price without price_year')
            if not v.get('price_source'):
                problems.append(f'{name}: observed_price without price_source')
            # Explicit empty check, not truthiness: an anchor of 0 miles means
            # the price was observed new, which is a real and usable datum.
            if str(v.get('observed_price_odometer', '')).strip() == '':
                problems.append(f'{name}: observed_price without '
                                f'observed_price_odometer -- the mileage a price '
                                f'was measured at is what lets the buy point move')
        else:
            # A placeholder carrying a year or a source claims provenance it does
            # not have. It would render identically to a verified row.
            for orphan in ('price_year', 'price_source'):
                if v.get(orphan):
                    problems.append(f'{name}: {orphan} set on a placeholder price; '
                                    f'only observed_price may claim one')
        if v.get('msrp'):
            if not v.get('msrp_year'):
                problems.append(f'{name}: msrp without msrp_year')
            if not v.get('msrp_trim'):
                problems.append(f'{name}: msrp without msrp_trim -- trim '
                                f'unstated, and trims span $7,655 on one nameplate')
            if not v.get('msrp_source'):
                problems.append(f'{name}: msrp without msrp_source')
        else:
            # Same rule as above, applied to the reference columns. Metadata
            # describing a figure that is not there is provenance for nothing.
            for orphan in ('msrp_year', 'msrp_trim', 'msrp_source'):
                if v.get(orphan):
                    problems.append(f'{name}: {orphan} set without an msrp')

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
            cap = category_ceiling(rows, v.get('category'), exclude=v)
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
    return problems


def num(x):
    """Drop the trailing .0 on whole numbers so 27.0 mpg serializes as 27."""
    return int(x) if float(x).is_integer() else float(x)


def scale(value, lo, hi, invert=False):
    """Normalize to 0-100 across the dataset. Flat dataset scores everything 100."""
    if hi == lo:
        return 100.0
    pct = (hi - value if invert else value - lo) / (hi - lo)
    return round(100 * pct, 1)


def load():
    rows = []
    with open(ROOT / 'data' / 'vehicles.csv', newline='') as fh:
        for r in csv.DictReader(fh):
            rows.append(dict(
                r, tier=int(r['tier']), price=float(r['price']),
                mpg=float(r['mpg']), deprec_5yr=float(r['deprec_5yr']),
                quality=float(r['quality']), longevity=float(r['longevity']),
                reliability=float(r['reliability']), comfort=float(r['comfort']),
                db55=float(r['db55']), heavy=r['heavy'] == 'true',
                db_measured=r['db_measured'] == 'true'))
    if not rows:
        sys.exit('data/vehicles.csv has no rows')
    return rows


def build_models(rows, inp):
    mpgs = [v['mpg'] for v in rows]
    mlo, mhi = min(mpgs), max(mpgs)

    out = []
    for v in rows:
        price, basis = buy_price(v, inp)
        out.append({
            'name': v['name'], 'cat': v['category'], 'tier': v['tier'],
            'key': row_key(v),
            'trimName': v.get('trim_name') or '',
            'price': int(round(price)), 'priceBasis': basis,
            'priceYear': v.get('price_year') or '', 'mpg': num(v['mpg']), 'fuel': v['fuel'],
            'gvwr': v['gvwr_note'],
            'deprec5yr': float(v['deprec_5yr']),
            'tireClass': 'Truck' if v['tire_class'] == 'Truck' else 'Crossover',
            'observedPrice': float(v['observed_price']) if v.get('observed_price') else None,
            'observedAt': (float(v['observed_price_odometer'])
                           if str(v.get('observed_price_odometer', '')).strip() != ''
                           else None),
            'quality': num(v['quality']), 'longevity': num(v['longevity']),
            'efficiency': scale(v['mpg'], mlo, mhi),
            'reliability': num(v['reliability']), 'comfort': num(v['comfort']),
            'db55': num(v['db55']), 'dbMeasured': v['db_measured'],
            'transName': v['transmission'], 'engineName': v['engine'],
            'longSource': v['longevity_source'], 'risk': v['risk'],
            'heavy': v['heavy'],
        })
    return out


def strip_for_oracle(rows):
    """Rows with observed_price and msrp cleared, before build_models runs.

    The workbook's published figures were computed on the original
    placeholder prices, so comparing against it requires nulling both columns
    first -- build_models() resolves buy_price into the emitted 'price'
    field, so stripping observedPrice from an already-built model cannot
    recover the placeholder.
    """
    return [dict(r, msrp='', observed_price='') for r in rows]


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


def dump_variants(rows, inp):
    """The two model-array variants the JS engine test feeds to VA.costPerMile.

    'full' is the real data; 'workbook_oracle' runs strip_for_oracle() first.
    Shared by test_build.py's parity check and freeze_fixture.py's
    regeneration so both hand the engine exactly the same input.
    """
    return {
        'full': build_models(rows, inp),
        'workbook_oracle': build_models(strip_for_oracle(rows), inp),
    }


ENGINE_START = '/* Cost engine.'


def render(html, models, inputs, engine_src):
    """Inline the engine, the inputs, and the raw rows into the page.

    engine.js is a real source file so the Node test can import it directly
    rather than scraping a <script> block out of the HTML. Inlining here is
    what keeps the published page a single file with no dependencies.

    Idempotent: the engine block is re-emitted on every build, so a repeat
    build must replace the previously-inlined copy rather than stack another
    one in front of it. `start` is found from the engine sentinel when
    present, MARKER otherwise. `end` is always resolved from MARKER's own
    position, searched forward from `start` -- engine.js contains a '];' of
    its own (repairReserve's band array), so anchoring the search to MARKER
    rather than to `start` keeps a rebuild from truncating mid-engine.

    ENGINE_START has to actually be in engine.js, or the idempotency check
    above silently stops finding the previously inlined copy -- `start` falls
    back to MARKER and every build stacks another engine copy in front of the
    last one instead of replacing it.
    """
    assert ENGINE_START in engine_src, (
        f'engine.js no longer starts with {ENGINE_START!r} -- its header '
        'comment changed, and build.py can no longer locate the inlined '
        'block to replace it')
    if ENGINE_START in html:
        start = html.index(ENGINE_START)
    else:
        start = html.index(MARKER)
    marker = html.index(MARKER, start)
    end = html.index('];', marker) + 2
    payload = json.dumps(models, separators=(',', ':'), ensure_ascii=False)
    block = (engine_src.rstrip() + '\n'
             + 'var INPUTS = ' + json.dumps(inputs, separators=(',', ':')) + ';\n'
             + MARKER + payload + ';')
    return html[:start] + block + html[end:]


def render_current(rows):
    """Render index.html from `rows` and the sources on disk right now.

    Returns (on_disk_html, freshly_rendered_html, models). `--check` below and
    test_build.py's stale-page guard both need "what does index.html look
    like if we build it this instant" -- this is the one place that answers
    that, so the two call paths cannot silently diverge into two different
    ideas of what "up to date" means.
    """
    html = (ROOT / 'index.html').read_text()
    engine_src = (ROOT / 'engine.js').read_text()
    models = build_models(rows, INPUTS)
    updated = render(html, models, INPUTS, engine_src)
    return html, updated, models


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--check', action='store_true',
                    help='exit 1 if index.html is stale instead of rewriting it')
    args = ap.parse_args()

    rows = load()
    problems = price_problems(rows)
    if problems:
        sys.exit('price provenance is incomplete:\n  '
                 + '\n  '.join(problems))

    html, updated, models = render_current(rows)
    observed = sum(1 for m in models if m['priceBasis'] == 'observed')

    if args.check:
        if updated != html:
            sys.exit('index.html is stale -- run: python3 build.py')
        print(f'index.html up to date ({len(models)} vehicles, '
              f'{observed} observed / {len(models) - observed} placeholder)')
        return
    (ROOT / 'index.html').write_text(updated)
    print(f'wrote index.html ({len(models)} vehicles, '
          f'{observed} observed / {len(models) - observed} placeholder)')


if __name__ == '__main__':
    main()
