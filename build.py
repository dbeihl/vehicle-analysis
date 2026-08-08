#!/usr/bin/env python3
"""Generate the MODELS array in index.html from data/vehicles.csv.

The CSV holds only observations and judgments. Everything the model computes --
cost per mile, the 0-100 cost and efficiency axes -- is derived here, so adding
a row means adding a row, not hand-recomputing nine columns in two places.

    python3 build.py           rewrite index.html in place
    python3 build.py --check   verify index.html is up to date (exit 1 if not)

Mirrors the Models tab of vehicle-turnover-planner.xlsx. Sources for every
assumption are on that workbook's Sources tab.
"""
import argparse
import csv
import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).parent
INPUTS = json.loads((ROOT / 'data' / 'inputs.json').read_text())
MARKER = 'const MODELS = '


def retention_index(odometer, anchors):
    """Linear interpolation over the odometer/median-price anchor table.

    Depreciation!C21:C22. Indexed against the zero-mile anchor, so a vehicle at
    0 miles is 1.0. Flat extrapolation past the ends of the table.
    """
    base = anchors[0][1]
    if odometer <= anchors[0][0]:
        return anchors[0][1] / base
    for (x0, y0), (x1, y1) in zip(anchors, anchors[1:]):
        if odometer <= x1:
            span = (odometer - x0) / (x1 - x0)
            return (y0 + span * (y1 - y0)) / base
    return anchors[-1][1] / base


def repair_reserve(inp):
    """Repair dollars per mile, weighted by cycle miles in each band (Inputs!C29)."""
    buy, sell = inp['buy_odometer'], inp['sell_odometer']
    rates = inp['repair_reserve_per_mile']
    bands = [(max(0, min(sell, 100000) - buy), rates['under_100k']),
             (max(0, min(sell, 150000) - max(buy, 100000)), rates['100k_to_150k']),
             (max(0, sell - max(buy, 150000)), rates['over_150k'])]
    miles = sell - buy
    return sum(m * r for m, r in bands) / miles


def resale_multiplier(v, inp):
    """Resale strength relative to the industry-average 5-year depreciation."""
    return (1 - v['deprec_5yr']) / (1 - inp['industry_avg_5yr_deprec'])


def buy_price(v, inp):
    """Price at the buy odometer.

    Derived from MSRP through the retention curve when a verified MSRP exists,
    so the number carries a year, a trim, and a source. Rows without one fall
    back to the original placeholder, which records none of those and therefore
    cannot be checked -- that is the point of the msrp columns.
    """
    if v.get('observed_price'):
        return float(v['observed_price']), 'observed'   # a real listing beats any model
    if not v.get('msrp'):
        return float(v['price']), 'placeholder'
    idx = retention_index(inp['buy_odometer'], inp['retention_anchors'])
    return float(v['msrp']) * idx * resale_multiplier(v, inp), 'msrp'


def cost_per_mile(v, inp):
    """All-in dollars per mile over one ownership cycle. Mirrors Models!AB."""
    miles = inp['sell_odometer'] - inp['buy_odometer']
    years = miles / inp['annual_miles']
    anchors = inp['retention_anchors']

    price, _ = buy_price(v, inp)
    resale_mult = resale_multiplier(v, inp)
    ratio = (retention_index(inp['sell_odometer'], anchors)
             / retention_index(inp['buy_odometer'], anchors))
    resale = min(price, price * ratio * resale_mult)

    fuel = (inp['diesel_per_gal'] if v['fuel'] == 'Diesel'
            else inp['gas_per_gal']) / v['mpg']
    tires = (inp['tire_set_truck'] if v['tire_class'] == 'Truck'
             else inp['tire_set_crossover']) / inp['tire_life_miles']

    if inp['financing_mode'] == 'cash':
        capital = (price + resale) / 2 * inp['cash_opportunity_rate']
    else:
        financed = price * (1 - inp['down_payment_pct'])
        capital = (financed * inp['avg_outstanding_balance_factor'] * inp['loan_apr']
                   + price * inp['down_payment_pct'] * inp['cash_opportunity_rate'])

    return ((price - resale) / miles                           # depreciation
            + fuel + tires
            + inp['scheduled_maint_per_mile']
            + repair_reserve(inp)
            + (inp['insurance_per_year'] + inp['registration_per_year'])
            / inp['annual_miles']
            + price * inp['sales_tax_rate'] / miles             # one-time, spread
            + capital * years / miles)


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
    cpms = [cost_per_mile(v, inp) for v in rows]
    lo, hi = min(cpms), max(cpms)
    mpgs = [v['mpg'] for v in rows]
    mlo, mhi = min(mpgs), max(mpgs)

    out = []
    for v, cpm in zip(rows, cpms):
        out.append({
            'name': v['name'], 'cat': v['category'], 'tier': v['tier'],
            'price': int(round(buy_price(v, inp)[0])), 'mpg': num(v['mpg']), 'fuel': v['fuel'],
            'gvwr': v['gvwr_note'],
            'cpm': round(cpm, 3),
            'peryr': round(cpm * inp['annual_miles']),
            'cost': scale(cpm, lo, hi, invert=True),
            'quality': num(v['quality']), 'longevity': num(v['longevity']),
            'efficiency': scale(v['mpg'], mlo, mhi),
            'reliability': num(v['reliability']), 'comfort': num(v['comfort']),
            'db55': num(v['db55']), 'dbMeasured': v['db_measured'],
            'transName': v['transmission'], 'engineName': v['engine'],
            'longSource': v['longevity_source'], 'risk': v['risk'],
            'heavy': v['heavy'],
        })
    return out


def render(html, models):
    start = html.index(MARKER)
    end = html.index('];', start) + 2
    payload = json.dumps(models, separators=(',', ':'), ensure_ascii=False)
    return html[:start] + MARKER + payload + ';' + html[end:]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--check', action='store_true',
                    help='exit 1 if index.html is stale instead of rewriting it')
    args = ap.parse_args()

    path = ROOT / 'index.html'
    html = path.read_text()
    models = build_models(load(), INPUTS)
    updated = render(html, models)

    if args.check:
        if updated != html:
            sys.exit('index.html is stale -- run: python3 build.py')
        print(f'index.html up to date ({len(models)} vehicles)')
        return
    path.write_text(updated)
    print(f'wrote index.html ({len(models)} vehicles)')


if __name__ == '__main__':
    main()
