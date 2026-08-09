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
                          'observedPrice', 'observedAt')


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


def price_problems(rows):
    """Data-integrity checks on price provenance. Empty list means clean.

    Unknown provenance has to be an error rather than a silent default, or the
    check is decorative -- a placeholder that nobody flags reads exactly like a
    verified figure once it reaches the page.
    """
    problems = []
    for v in rows:
        name = v['name']
        if v.get('observed_price'):
            if not v.get('price_year'):
                problems.append(f'{name}: observed_price without price_year')
            if not v.get('price_source'):
                problems.append(f'{name}: observed_price without price_source')
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
            'price': int(round(price)), 'priceBasis': basis,
            'priceYear': v.get('price_year') or '', 'mpg': num(v['mpg']), 'fuel': v['fuel'],
            'gvwr': v['gvwr_note'],
            'deprec5yr': float(v['deprec_5yr']),
            'tireClass': 'Truck' if v['tire_class'] == 'Truck' else 'Crossover',
            'observedPrice': float(v['observed_price']) if v.get('observed_price') else None,
            'observedAt': float(v['observed_price_odometer']) if v.get('observed_price_odometer') else None,
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
